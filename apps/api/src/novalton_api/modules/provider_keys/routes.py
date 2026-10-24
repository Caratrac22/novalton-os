"""Scoped personal BYOK storage, deliberately disconnected from paid generation."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.durable_dispatch.saas_access import require_saas_access
from novalton_api.modules.local_auth.service import get_session, verify_sensitive_password
from novalton_api.modules.provider_keys.models import ProviderKey
from novalton_api.modules.provider_keys.vault import Keyring, VaultUnavailable

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/provider-keys", tags=["provider-keys"]
)
Session = Annotated[AsyncSession, Depends(get_async_session)]
Human = Annotated[OperatorAuthority | None, Depends(require_saas_access)]
ProviderName = Literal["openrouter", "openai_compatible"]


class SecretInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    secret: str = Field(min_length=8, max_length=4096)
    current_password: str = Field(min_length=1, max_length=128)


class StateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    current_password: str = Field(min_length=1, max_length=128)


class RemoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: str = Field(min_length=1, max_length=128)


def _operator(operator: OperatorAuthority | None) -> OperatorAuthority:
    if operator is None:
        raise ApplicationError("saas_auth_required", "Session required", status_code=401)
    return operator


def _vault() -> Keyring:
    try:
        return Keyring.from_environment()
    except VaultUnavailable as exc:
        raise ApplicationError("vault_unavailable", "Coffre indisponible", status_code=503) from exc


async def _reauth(
    session: AsyncSession,
    operator: OperatorAuthority | None,
    authorization: str | None,
    password: str,
) -> UUID:
    user_id = _operator(operator).user_id
    if not authorization or not authorization.startswith("Bearer nvl_"):
        raise ApplicationError("local_account_required", "Compte local requis", status_code=403)
    token = authorization.removeprefix("Bearer ")
    active = await get_session(session, token, lock=True)
    if active.user_id != user_id or active.created_at + timedelta(minutes=10) < datetime.now(UTC):
        raise ApplicationError(
            "reauth_required", "Reconnectez-vous avant de modifier les clés", status_code=401
        )
    await verify_sensitive_password(session, user_id=user_id, password=password)
    return user_id


async def _row(
    session: AsyncSession,
    *,
    owner: UUID,
    tenant: UUID,
    workspace: UUID,
    provider: ProviderName,
    lock: bool = False,
) -> ProviderKey | None:
    statement = select(ProviderKey).where(
        ProviderKey.owner_id == owner,
        ProviderKey.tenant_id == tenant,
        ProviderKey.workspace_id == workspace,
        ProviderKey.provider == provider,
        ProviderKey.revoked_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement.execution_options(populate_existing=True))


def _public(row: ProviderKey) -> dict[str, object]:
    return {
        "provider": row.provider,
        "configured": True,
        "enabled": row.enabled,
        "updated_at": row.updated_at,
        "billing": "BILLING_UNVERIFIED",
        "chat_enabled": False,
    }


async def _audit(
    session: AsyncSession,
    *,
    tenant: UUID,
    workspace: UUID,
    owner: UUID,
    action: str,
    provider: ProviderName,
) -> None:
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant,
            workspace_id=workspace,
            action=action,
            actor_type="local_user",
            actor_id=str(owner),
            outcome="success",
            metadata={"provider": provider},
        ),
        commit=False,
    )


@router.get("")
async def listing(
    tenant_id: UUID, workspace_id: UUID, session: Session, operator: Human
) -> dict[str, object]:
    owner = _operator(operator).user_id
    try:
        vault = Keyring.from_environment()
        available = True
    except VaultUnavailable:
        vault, available = None, False
    rows = (
        await session.scalars(
            select(ProviderKey).where(
                ProviderKey.owner_id == owner,
                ProviderKey.tenant_id == tenant_id,
                ProviderKey.workspace_id == workspace_id,
                ProviderKey.revoked_at.is_(None),
            )
        )
    ).all()
    return {
        "vault_available": available,
        "items": [
            {**_public(row), "key_available": bool(vault and row.key_id in vault.keys)}
            for row in rows
        ],
    }


@router.put("/{provider}")
async def put(
    provider: ProviderName,
    tenant_id: UUID,
    workspace_id: UUID,
    data: SecretInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    owner = await _reauth(session, operator, authorization, data.current_password)
    key_id, nonce, ciphertext = _vault().encrypt(
        data.secret, owner=owner, tenant=tenant_id, workspace=workspace_id, provider=provider
    )
    row = await _row(
        session, owner=owner, tenant=tenant_id, workspace=workspace_id, provider=provider, lock=True
    )
    if row is None:
        row = ProviderKey(
            owner_id=owner,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            provider=provider,
            key_id=key_id,
            nonce=nonce,
            ciphertext=ciphertext,
            enabled=False,
        )
        session.add(row)
    else:
        row.key_id, row.nonce, row.ciphertext, row.enabled = key_id, nonce, ciphertext, False
        row.updated_at = datetime.now(UTC)
    await session.flush()
    public = _public(row)
    await _audit(
        session,
        tenant=tenant_id,
        workspace=workspace_id,
        owner=owner,
        action="provider_key.replace",
        provider=provider,
    )
    await session.commit()
    return public


@router.patch("/{provider}")
async def toggle(
    provider: ProviderName,
    tenant_id: UUID,
    workspace_id: UUID,
    data: StateInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    owner = await _reauth(session, operator, authorization, data.current_password)
    vault = _vault()
    row = await _row(
        session, owner=owner, tenant=tenant_id, workspace=workspace_id, provider=provider, lock=True
    )
    if row is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    if data.enabled:
        try:
            vault.decrypt(
                row.key_id,
                row.nonce,
                row.ciphertext,
                owner=owner,
                tenant=tenant_id,
                workspace=workspace_id,
                provider=provider,
            )
        except VaultUnavailable as exc:
            raise ApplicationError(
                "vault_unavailable", "Coffre indisponible", status_code=503
            ) from exc
    row.enabled = data.enabled
    row.updated_at = datetime.now(UTC)
    public = _public(row)
    await _audit(
        session,
        tenant=tenant_id,
        workspace=workspace_id,
        owner=owner,
        action="provider_key.toggle",
        provider=provider,
    )
    await session.commit()
    return public


@router.delete("/{provider}", status_code=204)
async def remove(
    provider: ProviderName,
    tenant_id: UUID,
    workspace_id: UUID,
    data: RemoveInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    owner = await _reauth(session, operator, authorization, data.current_password)
    row = await _row(
        session, owner=owner, tenant=tenant_id, workspace=workspace_id, provider=provider, lock=True
    )
    if row is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    await session.execute(delete(ProviderKey).where(ProviderKey.id == row.id))
    await _audit(
        session,
        tenant=tenant_id,
        workspace=workspace_id,
        owner=owner,
        action="provider_key.remove",
        provider=provider,
    )
    await session.commit()
