"""A scoped, verified internal operator capability for dispatch control.

Only a trusted adapter calls authenticate_operator with the presented credential.
No HTTP endpoint, model tool or caller-supplied tenant UUID creates this authority.
The server stores only a SHA-256 digest of a high-entropy operator key.
"""

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.identity import (
    FederatedOperatorIdentity,
    HumanOperator,
    TenantOperatorMembership,
    WorkspaceOperatorPermission,
)

PERMISSIONS = frozenset(
    {
        "activation.configure",
        "dispatch.enqueue",
        "dispatch.read",
        "dispatch.cancel",
        "dispatch.resolve",
    }
)
_SEAL = object()


def _forbidden() -> ApplicationError:
    return ApplicationError(
        "dispatch_operator_forbidden", "Dispatch operator authority is unavailable", status_code=403
    )


def _configured() -> tuple[str, str, UUID, UUID, UUID, frozenset[str]]:
    settings = get_settings()
    values = (
        settings.durable_dispatch_operator_key_sha256,
        settings.durable_dispatch_operator_id,
        settings.durable_dispatch_operator_user_id,
        settings.durable_dispatch_operator_tenant_id,
        settings.durable_dispatch_operator_workspace_id,
    )
    if any(value is None for value in values):
        raise _forbidden()
    permissions = frozenset(
        item.strip()
        for item in settings.durable_dispatch_operator_permissions.split(",")
        if item.strip()
    )
    if not permissions or not permissions <= PERMISSIONS:
        raise _forbidden()
    digest, actor_id, user_id, tenant_id, workspace_id = values
    assert isinstance(digest, str) and isinstance(actor_id, str)
    assert isinstance(user_id, UUID)
    assert isinstance(tenant_id, UUID) and isinstance(workspace_id, UUID)
    return digest, actor_id, user_id, tenant_id, workspace_id, permissions


class OperatorAuthority:
    """Opaque in-process result of successful credential verification."""

    __slots__ = (
        "_seal",
        "_digest",
        "_label",
        "user_id",
        "actor_id",
        "tenant_id",
        "workspace_id",
        "permissions",
        "_issuer",
        "_subject",
        "_expires_at",
    )

    def __init__(
        self,
        seal: object,
        digest: str,
        actor_id: str,
        user_id: UUID,
        tenant_id: UUID,
        workspace_id: UUID,
        permissions: frozenset[str],
        issuer: str | None = None,
        subject: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        if seal is not _SEAL:
            raise _forbidden()
        self._seal = seal
        self._digest = digest
        self._label = actor_id
        self.user_id = user_id
        self.actor_id = str(user_id)
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.permissions = permissions
        self._issuer = issuer
        self._subject = subject
        self._expires_at = expires_at

    def require(self, permission: str, *, tenant_id: UUID, workspace_id: UUID) -> None:
        if self._issuer is not None:
            if (
                self._seal is not _SEAL
                or self._expires_at is None
                or datetime.now(UTC) >= self._expires_at
                or (tenant_id, workspace_id) != (self.tenant_id, self.workspace_id)
                or permission not in self.permissions
            ):
                raise _forbidden()
            return
        digest, actor_id, configured_user, configured_tenant, configured_workspace, permissions = (
            _configured()
        )
        if (
            self._seal is not _SEAL
            or not hmac.compare_digest(self._digest, digest)
            or self._label != actor_id
            or self.user_id != configured_user
            or (self.tenant_id, self.workspace_id) != (configured_tenant, configured_workspace)
            or self.permissions != permissions
            or (tenant_id, workspace_id) != (configured_tenant, configured_workspace)
            or permission not in permissions
        ):
            raise _forbidden()

    async def require_human(
        self,
        session: AsyncSession,
        permission: str,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        exclusive: bool = False,
    ) -> None:
        """Lock persisted membership through the decision's commit.

        A revocation UPDATE takes the conflicting lock. A previously issued
        capability never outlives an inactive user or workspace permission.
        """
        self.require(permission, tenant_id=tenant_id, workspace_id=workspace_id)
        user = await session.scalar(
            select(HumanOperator)
            .where(HumanOperator.id == self.user_id)
            .with_for_update(read=not exclusive)
            .execution_options(populate_existing=True)
        )
        membership = await session.scalar(
            select(TenantOperatorMembership)
            .where(
                TenantOperatorMembership.user_id == self.user_id,
                TenantOperatorMembership.tenant_id == tenant_id,
            )
            .with_for_update(read=not exclusive)
            .execution_options(populate_existing=True)
        )
        grant = await session.scalar(
            select(WorkspaceOperatorPermission)
            .where(
                WorkspaceOperatorPermission.user_id == self.user_id,
                WorkspaceOperatorPermission.tenant_id == tenant_id,
                WorkspaceOperatorPermission.workspace_id == workspace_id,
                WorkspaceOperatorPermission.permission == permission,
            )
            .with_for_update(read=not exclusive)
            .execution_options(populate_existing=True)
        )
        identity = None
        if self._issuer is not None:
            identity = await session.scalar(
                select(FederatedOperatorIdentity)
                .where(
                    FederatedOperatorIdentity.user_id == self.user_id,
                    FederatedOperatorIdentity.issuer == self._issuer,
                    FederatedOperatorIdentity.subject == self._subject,
                )
                .with_for_update(read=not exclusive)
                .execution_options(populate_existing=True)
            )
        if (
            user is None
            or not user.active
            or user.label != self._label
            or membership is None
            or not membership.active
            or grant is None
            or not grant.active
            or (self._issuer is not None and (identity is None or not identity.active))
        ):
            raise _forbidden()


def federated_operator_authority(
    *, user: HumanOperator, issuer: str, subject: str, expires_at: datetime,
    tenant_id: UUID, workspace_id: UUID,
) -> OperatorAuthority:
    """Construct only after an external signature and an exact subject binding are verified."""
    return OperatorAuthority(
        _SEAL, "", user.label, user.id, tenant_id, workspace_id, PERMISSIONS,
        issuer=issuer, subject=subject, expires_at=expires_at,
    )


async def require_active_dispatch_operator(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID
) -> None:
    """Fence new worker reservations when the activating human is revoked.

    Workers have no plaintext human credential. Their configured identity and
    activation permission are checked in the same transaction as the claim or
    provider reservation; shared locks serialize a concurrent revocation.
    Already engaged provider responses may still record their actual outcome.
    """
    _, label, user_id, configured_tenant, configured_workspace, permissions = _configured()
    if (tenant_id, workspace_id) != (
        configured_tenant,
        configured_workspace,
    ) or "activation.configure" not in permissions:
        raise _forbidden()
    user = await session.scalar(
        select(HumanOperator)
        .where(HumanOperator.id == user_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    membership = await session.scalar(
        select(TenantOperatorMembership)
        .where(
            TenantOperatorMembership.user_id == user_id,
            TenantOperatorMembership.tenant_id == tenant_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    grant = await session.scalar(
        select(WorkspaceOperatorPermission)
        .where(
            WorkspaceOperatorPermission.user_id == user_id,
            WorkspaceOperatorPermission.tenant_id == tenant_id,
            WorkspaceOperatorPermission.workspace_id == workspace_id,
            WorkspaceOperatorPermission.permission == "activation.configure",
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        user is None
        or not user.active
        or user.label != label
        or membership is None
        or not membership.active
        or grant is None
        or not grant.active
    ):
        raise _forbidden()


def authenticate_operator(credential: str) -> OperatorAuthority:
    """Verify a high-entropy key in constant time against process configuration.

    The plaintext credential is never retained, persisted, logged or audited.
    Rotate the configured digest to revoke previously issued capabilities.
    """
    digest, actor_id, user_id, tenant_id, workspace_id, permissions = _configured()
    if not isinstance(credential, str) or len(credential) < 32:
        raise _forbidden()
    candidate = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(candidate, digest):
        raise _forbidden()
    return OperatorAuthority(_SEAL, digest, actor_id, user_id, tenant_id, workspace_id, permissions)
