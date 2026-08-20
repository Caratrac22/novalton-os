"""SQL owned by the runtime events module."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.runtime_events.models import RuntimeEvent


async def append_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    event_type: str,
    source: str,
    occurred_at: datetime | None,
    correlation_id: str | None,
    project_id: UUID | None,
    task_id: UUID | None,
    payload: dict[str, object] | None,
) -> RuntimeEvent:
    event = RuntimeEvent(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        event_type=event_type,
        source=source,
        correlation_id=correlation_id,
        project_id=project_id,
        task_id=task_id,
        payload=payload,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    session.add(event)
    await session.flush()
    return event


async def list_recent_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
) -> list[RuntimeEvent]:
    result = await session.scalars(
        select(RuntimeEvent)
        .where(
            RuntimeEvent.tenant_id == tenant_id,
            RuntimeEvent.workspace_id == workspace_id,
        )
        .order_by(RuntimeEvent.occurred_at.desc(), RuntimeEvent.id.desc())
        .limit(limit)
    )
    return list(result)
