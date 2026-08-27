"""Explicit workspace-scoped structured-memory queries."""

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novalton_api.modules.memories.models import MemoryRecord


async def create_memory(session: AsyncSession, *, memory: MemoryRecord) -> MemoryRecord:
    session.add(memory)
    await session.flush()
    return memory


async def get_memory(
    session: AsyncSession, *, workspace_id: UUID, memory_id: UUID
) -> MemoryRecord | None:
    return await session.scalar(
        select(MemoryRecord)
        .where(MemoryRecord.workspace_id == workspace_id, MemoryRecord.id == memory_id)
        .options(selectinload(MemoryRecord.provenance))
    )


async def list_memories(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
    project_id: UUID | None,
    task_id: UUID | None,
    workflow_run_id: UUID | None,
    kind: str | None,
    knowledge_state: str | None,
    lifecycle: str | None,
) -> list[MemoryRecord]:
    statement: Select[tuple[MemoryRecord]] = select(MemoryRecord).where(
        MemoryRecord.workspace_id == workspace_id
    )
    for column, value in (
        (MemoryRecord.project_id, project_id),
        (MemoryRecord.task_id, task_id),
        (MemoryRecord.workflow_run_id, workflow_run_id),
        (MemoryRecord.kind, kind),
        (MemoryRecord.knowledge_state, knowledge_state),
        (MemoryRecord.lifecycle, lifecycle),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return list(
        await session.scalars(
            statement.options(selectinload(MemoryRecord.provenance))
            .order_by(MemoryRecord.created_at.asc(), MemoryRecord.id.asc())
            .limit(limit)
            .offset(offset)
        )
    )
