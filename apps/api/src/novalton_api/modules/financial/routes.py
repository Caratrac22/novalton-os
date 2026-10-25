"""Explicit, scoped human policy management; never starts a provider call."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.durable_dispatch.saas_access import require_saas_access
from novalton_api.modules.financial.models import FinancialAuthorization
from novalton_api.modules.financial.service import scoped_authorization
from novalton_api.modules.local_auth.service import get_session, verify_sensitive_password
from novalton_api.modules.projects.models import Project

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}/financial-authorizations",
    tags=["financial-authorizations"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]
Human = Annotated[OperatorAuthority | None, Depends(require_saas_access)]


class AuthorizeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirmation: Literal["AUTHORIZE_ESTIMATED_EXPOSURE"]
    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    model_id: str = Field(min_length=1, max_length=256)
    currency: Literal["USD"]
    request_limit: int = Field(gt=0, le=100_000)
    token_limit: int = Field(gt=0, le=100_000_000)
    estimated_limit: Decimal = Field(gt=0, max_digits=20, decimal_places=10, strict=False)
    expires_at: datetime = Field(strict=False)
    current_password: str = Field(min_length=1, max_length=128)


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current_password: str = Field(min_length=1, max_length=128)


def human(operator: OperatorAuthority | None) -> OperatorAuthority:
    if operator is None:
        raise ApplicationError("saas_auth_required", "Session required", status_code=401)
    return operator


async def reauth(
    session: AsyncSession,
    operator: OperatorAuthority,
    authorization: str | None,
    password: str,
) -> None:
    if not authorization or not authorization.startswith("Bearer nvl_"):
        raise ApplicationError("local_account_required", "Compte local requis", status_code=403)
    active = await get_session(session, authorization.removeprefix("Bearer "), lock=True)
    if active.user_id != operator.user_id or active.created_at + timedelta(
        minutes=10
    ) < datetime.now(UTC):
        raise ApplicationError("reauth_required", "Reconnectez-vous", status_code=401)
    await verify_sensitive_password(session, user_id=operator.user_id, password=password)


def public(row: FinancialAuthorization) -> dict[str, object]:
    return {
        "id": row.id,
        "version": row.version,
        "provider_id": row.provider_id,
        "model_id": row.model_id,
        "currency": row.currency,
        "request_limit": row.request_limit,
        "request_count": row.request_count,
        "token_limit": row.token_limit,
        "reserved_tokens": row.reserved_tokens,
        "estimated_limit": row.estimated_limit,
        "reserved_estimate": row.reserved_estimate,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "billing": "BILLING_UNVERIFIED",
        "paid_generation_enabled": False,
    }


@router.post("", status_code=201)
async def authorize(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    data: AuthorizeInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    owner = human(operator)
    await owner.require_human(
        session,
        "workspace.write",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        exclusive=True,
    )
    await reauth(session, owner, authorization, data.current_password)
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
            Project.status == "ACTIVE",
        )
    )
    if project is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    now = datetime.now(UTC)
    if data.expires_at.tzinfo is None or not now < data.expires_at <= now + timedelta(days=30):
        raise ApplicationError("invalid_financial_expiry", "Expiration invalide", status_code=422)
    row = FinancialAuthorization(
        owner_id=owner.user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        provider_id=data.provider_id,
        model_id=data.model_id,
        currency=data.currency,
        version=1,
        request_limit=data.request_limit,
        request_count=0,
        token_limit=data.token_limit,
        reserved_tokens=0,
        estimated_limit=data.estimated_limit,
        reserved_estimate=Decimal(0),
        expires_at=data.expires_at,
    )
    session.add(row)
    await session.flush()
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            resource_type="project",
            resource_id=project_id,
            action="financial.authorization.created",
            actor_type="local_user",
            actor_id=str(owner.user_id),
            outcome="success",
            metadata={"financial_policy_id": str(row.id), "version": 1},
        ),
        commit=False,
    )
    await session.commit()
    return public(row)


@router.get("")
async def listing(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    owner = human(operator)
    project = await session.scalar(
        select(Project.id).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    rows = (
        await session.scalars(
            select(FinancialAuthorization)
            .where(
                FinancialAuthorization.owner_id == owner.user_id,
                FinancialAuthorization.tenant_id == tenant_id,
                FinancialAuthorization.workspace_id == workspace_id,
                FinancialAuthorization.project_id == project_id,
            )
            .order_by(FinancialAuthorization.created_at.desc())
            .limit(100)
        )
    ).all()
    return {"items": [public(row) for row in rows]}


@router.post("/{authorization_id}/revoke")
async def revoke(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    authorization_id: UUID,
    data: RevokeInput,
    session: Session,
    operator: Human,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    owner = human(operator)
    await owner.require_human(
        session,
        "workspace.write",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        exclusive=True,
    )
    await reauth(session, owner, authorization, data.current_password)
    row = await scoped_authorization(
        session,
        authorization_id=authorization_id,
        owner_id=owner.user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        lock=True,
    )
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        row.version += 1
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project_id,
                resource_type="project",
                resource_id=project_id,
                action="financial.authorization.revoked",
                actor_type="local_user",
                actor_id=str(owner.user_id),
                outcome="success",
                metadata={"financial_policy_id": str(row.id), "version": row.version},
            ),
            commit=False,
        )
    await session.commit()
    return public(row)
