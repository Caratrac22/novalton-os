"""Scoped SQL operations for model runs."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.model_usage.models import ModelRun


async def create_run(session: AsyncSession, **values: object) -> ModelRun:
    run = ModelRun(**values)
    session.add(run)
    await session.flush()
    return run


async def get_scoped_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, model_run_id: UUID
) -> ModelRun | None:
    return await session.scalar(
        select(ModelRun).where(
            ModelRun.id == model_run_id,
            ModelRun.tenant_id == tenant_id,
            ModelRun.workspace_id == workspace_id,
        )
    )


async def list_scoped_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: str | None,
) -> list[ModelRun]:
    statement = select(ModelRun).where(
        ModelRun.tenant_id == tenant_id, ModelRun.workspace_id == workspace_id
    )
    if status is not None:
        statement = statement.where(ModelRun.status == status)
    result = await session.scalars(
        statement.order_by(ModelRun.created_at.desc(), ModelRun.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def transition_running(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    model_run_id: UUID,
    values: Mapping[str, Any],
) -> ModelRun | None:
    return await session.scalar(
        update(ModelRun)
        .where(
            ModelRun.id == model_run_id,
            ModelRun.tenant_id == tenant_id,
            ModelRun.workspace_id == workspace_id,
            ModelRun.status == "RUNNING",
        )
        .values(**values)
        .returning(ModelRun)
    )
