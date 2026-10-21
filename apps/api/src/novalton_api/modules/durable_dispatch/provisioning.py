"""Trusted, credential-verified operator handoff; deliberately no HTTP admin route."""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch.authority import database_now, denied
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.durable_dispatch.operator import PERMISSIONS, OperatorAuthority

_LABEL = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


async def rotate_operator(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    successor_id: UUID,
    successor_label: str,
    permissions: frozenset[str],
) -> HumanOperator:
    """Atomically revoke the old scoped grants and provision a fresh principal.

    The new secret and SHA-256 digest are supplied out of band to the trusted
    deployment. The old processes lose DB authority at commit, before any new
    process can use the successor configuration. A new UUID is mandatory: merely
    replacing a digest in process configuration cannot fence stale processes.
    """
    if (
        not isinstance(successor_id, UUID)
        or successor_id == operator.user_id
        or _LABEL.fullmatch(successor_label) is None
        or not permissions
        or not permissions <= PERMISSIONS
        or "activation.configure" not in permissions
        or not permissions <= operator.permissions
    ):
        raise denied("dispatch_operator_rotation_invalid")

    # Exclusive user/grant locks serialize concurrent rotations and decisions.
    await operator.require_human(
        session,
        "activation.configure",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        exclusive=True,
    )
    for permission in sorted(permissions - {"activation.configure"}):
        await operator.require_human(
            session,
            permission,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            exclusive=True,
        )
    if await session.get(HumanOperator, successor_id) is not None:
        raise denied("dispatch_operator_successor_exists")

    old_grants = list(
        await session.scalars(
            select(WorkspaceOperatorPermission)
            .where(
                WorkspaceOperatorPermission.user_id == operator.user_id,
                WorkspaceOperatorPermission.tenant_id == tenant_id,
                WorkspaceOperatorPermission.workspace_id == workspace_id,
            )
            .order_by(WorkspaceOperatorPermission.permission)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    now = await database_now(session)
    revoked_count = 0
    for grant in old_grants:
        if grant.active:
            grant.active = False
            grant.revoked_at = now
            revoked_count += 1
    successor = HumanOperator(id=successor_id, label=successor_label, active=True)
    session.add(successor)
    session.add_all(
        WorkspaceOperatorPermission(
            user_id=successor_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            permission=permission,
            active=True,
        )
        for permission in sorted(permissions)
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise denied("dispatch_operator_rotation_conflict") from None
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            action="dispatch.operator.rotate",
            actor_type="local_user",
            actor_id=operator.actor_id,
            outcome="success",
            metadata={
                "successor_id": str(successor_id),
                "permissions": sorted(permissions),
                "revoked_count": revoked_count,
            },
        ),
        commit=False,
    )
    await session.commit()
    return successor


async def revoke_permission(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    subject_id: UUID,
    permission: str,
) -> bool:
    """Revoke one exact scoped grant, retaining its row as durable evidence."""
    await operator.require_human(
        session,
        "activation.configure",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        exclusive=True,
    )
    if permission not in PERMISSIONS:
        raise denied("dispatch_operator_permission_invalid")
    grant = await session.scalar(
        select(WorkspaceOperatorPermission)
        .where(
            WorkspaceOperatorPermission.user_id == subject_id,
            WorkspaceOperatorPermission.tenant_id == tenant_id,
            WorkspaceOperatorPermission.workspace_id == workspace_id,
            WorkspaceOperatorPermission.permission == permission,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        raise denied("dispatch_operator_grant_missing")
    if not grant.active:
        await session.commit()
        return False
    grant.active = False
    grant.revoked_at = await database_now(session)
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            action="dispatch.operator.permission.revoke",
            actor_type="local_user",
            actor_id=operator.actor_id,
            outcome="success",
            metadata={"subject_id": str(subject_id), "permission": permission},
        ),
        commit=False,
    )
    await session.commit()
    return True
