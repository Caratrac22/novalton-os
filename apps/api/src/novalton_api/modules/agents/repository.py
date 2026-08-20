"""Explicit scoped SQL for definitions and agent runs."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from novalton_api.modules.agents.models import AgentDefinition, AgentRun


async def create_definition(session: AsyncSession, **values: object) -> AgentDefinition:
    definition = AgentDefinition(**values)
    session.add(definition)
    await session.flush()
    return definition


async def get_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, definition_id: UUID
) -> AgentDefinition | None:
    return await session.scalar(
        select(AgentDefinition).where(
            AgentDefinition.id == definition_id,
            AgentDefinition.tenant_id == tenant_id,
            AgentDefinition.workspace_id == workspace_id,
        )
    )


async def latest_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, slug: str
) -> AgentDefinition | None:
    return await session.scalar(
        select(AgentDefinition)
        .where(
            AgentDefinition.tenant_id == tenant_id,
            AgentDefinition.workspace_id == workspace_id,
            AgentDefinition.slug == slug,
        )
        .order_by(AgentDefinition.version.desc())
        .limit(1)
    )


async def list_definitions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    all_versions: bool,
) -> list[AgentDefinition]:
    statement = select(AgentDefinition).where(
        AgentDefinition.tenant_id == tenant_id, AgentDefinition.workspace_id == workspace_id
    )
    if not all_versions:
        candidate = aliased(AgentDefinition)
        latest_version = (
            select(func.max(candidate.version))
            .where(
                candidate.tenant_id == tenant_id,
                candidate.workspace_id == workspace_id,
                candidate.slug == AgentDefinition.slug,
            )
            .correlate(AgentDefinition)
            .scalar_subquery()
        )
        statement = statement.where(AgentDefinition.version == latest_version)
    rows = await session.scalars(
        statement.order_by(AgentDefinition.slug.asc(), AgentDefinition.version.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


async def create_run(session: AsyncSession, **values: object) -> AgentRun:
    run = AgentRun(**values)
    session.add(run)
    await session.flush()
    return run


async def get_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.tenant_id == tenant_id,
            AgentRun.workspace_id == workspace_id,
        )
    )


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: str | None,
) -> list[AgentRun]:
    statement = select(AgentRun).where(
        AgentRun.tenant_id == tenant_id, AgentRun.workspace_id == workspace_id
    )
    if status is not None:
        statement = statement.where(AgentRun.status == status)
    rows = await session.scalars(
        statement.order_by(AgentRun.created_at.desc(), AgentRun.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


async def transition_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    expected_status: str,
    values: Mapping[str, Any],
) -> AgentRun | None:
    return await session.scalar(
        update(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.tenant_id == tenant_id,
            AgentRun.workspace_id == workspace_id,
            AgentRun.status == expected_status,
        )
        .values(**values)
        .returning(AgentRun)
    )
