"""Explicit workspace-scoped structured-memory queries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from novalton_api.modules.memories.models import MemoryRecord

DEFAULT_KNOWLEDGE_STATES = (
    "CONFIRMED_FACT",
    "OBSERVED_FACT",
    "INFERENCE",
    "HYPOTHESIS",
    "DISPUTED",
)


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


async def retrieve_memories(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    as_of: datetime,
    query: str | None,
    project_id: UUID | None,
    task_id: UUID | None,
    workflow_run_id: UUID | None,
    kinds: tuple[str, ...] | None,
    knowledge_states: tuple[str, ...] | None,
    lifecycle: tuple[str, ...] | None,
    min_confidence: float | None,
    min_importance: int | None,
    limit: int,
) -> list[tuple[MemoryRecord, float | None]]:
    """Retrieve temporally admissible context without changing inventory semantics."""

    statement: Select[tuple[MemoryRecord]] = select(MemoryRecord).where(
        MemoryRecord.workspace_id == workspace_id,
        MemoryRecord.valid_from <= as_of,
        (MemoryRecord.valid_to.is_(None) | (MemoryRecord.valid_to > as_of)),
    )
    for column, value in (
        (MemoryRecord.project_id, project_id),
        (MemoryRecord.task_id, task_id),
        (MemoryRecord.workflow_run_id, workflow_run_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if kinds is not None:
        statement = statement.where(MemoryRecord.kind.in_(kinds))
    statement = statement.where(
        MemoryRecord.knowledge_state.in_(knowledge_states or DEFAULT_KNOWLEDGE_STATES)
    )
    statement = statement.where(MemoryRecord.lifecycle.in_(lifecycle or ("ACTIVE",)))
    if min_confidence is not None:
        statement = statement.where(MemoryRecord.confidence >= min_confidence)
    if min_importance is not None:
        statement = statement.where(MemoryRecord.importance >= min_importance)

    if query is None:
        rows = await session.execute(
            statement.options(selectinload(MemoryRecord.provenance))
            .order_by(
                MemoryRecord.importance.desc(),
                MemoryRecord.valid_from.desc(),
                MemoryRecord.created_at.desc(),
                MemoryRecord.id.asc(),
            )
            .limit(limit)
        )
        return [(memory, None) for memory in rows.scalars()]

    vector = func.to_tsvector("simple", MemoryRecord.statement)
    tsquery = func.websearch_to_tsquery("simple", query)
    lexical_relevance = func.ts_rank(vector, tsquery).label("lexical_relevance")
    rows = await session.execute(
        statement.add_columns(lexical_relevance)
        .where(vector.op("@@")(tsquery))
        .options(selectinload(MemoryRecord.provenance))
        .order_by(
            lexical_relevance.desc(),
            MemoryRecord.importance.desc(),
            MemoryRecord.valid_from.desc(),
            MemoryRecord.id.asc(),
        )
        .limit(limit)
    )
    return [(memory, float(rank)) for memory, rank in rows]
