"""SQL owned by the audit module."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.audit.models import AuditRecord


async def append_record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    action: str,
    actor_type: str,
    actor_id: str | None,
    outcome: str,
    resource_type: str | None,
    resource_id: UUID | None,
    project_id: UUID | None,
    task_id: UUID | None,
    correlation_id: str | None,
    occurred_at: datetime | None,
    metadata_json: dict[str, object] | None,
) -> AuditRecord:
    record = AuditRecord(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        outcome=outcome,
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
        task_id=task_id,
        correlation_id=correlation_id,
        metadata_json=metadata_json,
    )
    if occurred_at is not None:
        record.occurred_at = occurred_at
    session.add(record)
    await session.flush()
    return record


async def list_recent_records(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
) -> list[AuditRecord]:
    statement = select(AuditRecord).where(
        AuditRecord.tenant_id == tenant_id,
        AuditRecord.workspace_id == workspace_id,
    )
    if action is not None:
        statement = statement.where(AuditRecord.action == action)
    if resource_type is not None:
        statement = statement.where(AuditRecord.resource_type == resource_type)
    if resource_id is not None:
        statement = statement.where(AuditRecord.resource_id == resource_id)
    result = await session.scalars(
        statement.order_by(AuditRecord.occurred_at.desc(), AuditRecord.id.desc()).limit(limit)
    )
    return list(result)
