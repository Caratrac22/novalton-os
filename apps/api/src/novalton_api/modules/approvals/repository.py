"""SQL owned by the approvals module."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.approvals.models import ApprovalRequest


async def create_approval(session: AsyncSession, **values: object) -> ApprovalRequest:
    approval = ApprovalRequest(**values)
    session.add(approval)
    await session.flush()
    return approval


async def get_scoped_approval(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    for_update: bool = False,
) -> ApprovalRequest | None:
    statement = select(ApprovalRequest).where(
        ApprovalRequest.tenant_id == tenant_id,
        ApprovalRequest.workspace_id == workspace_id,
        ApprovalRequest.id == approval_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def list_scoped_approvals(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: str | None,
) -> list[ApprovalRequest]:
    statement = select(ApprovalRequest).where(
        ApprovalRequest.tenant_id == tenant_id,
        ApprovalRequest.workspace_id == workspace_id,
    )
    if status is not None:
        statement = statement.where(ApprovalRequest.status == status)
    result = await session.scalars(
        statement.order_by(ApprovalRequest.requested_at.desc(), ApprovalRequest.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def decide_pending(
    session: AsyncSession,
    *,
    approval_id: UUID,
    status: str,
    decided_at: datetime,
) -> ApprovalRequest | None:
    return await session.scalar(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id, ApprovalRequest.status == "PENDING")
        .values(
            status=status,
            decision_actor_type="local_user",
            decision_actor_id=None,
            decided_at=decided_at,
        )
        .returning(ApprovalRequest)
    )
