"""All SQL for the persistent model catalog."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.model_catalog.models import ModelDefinition


async def list_models(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    provider_id: str | None,
    status: str | None,
) -> list[ModelDefinition]:
    statement = select(ModelDefinition)
    if provider_id is not None:
        statement = statement.where(ModelDefinition.provider_id == provider_id)
    if status is not None:
        statement = statement.where(ModelDefinition.status == status)
    result = await session.scalars(
        statement.order_by(
            ModelDefinition.provider_id.asc(),
            ModelDefinition.provider_model_id.asc(),
            ModelDefinition.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def get_model(session: AsyncSession, *, model_id: UUID) -> ModelDefinition | None:
    return await session.get(ModelDefinition, model_id)


async def list_routing_candidates(session: AsyncSession) -> list[ModelDefinition]:
    """Return the complete authoritative catalog in stable identity order."""
    result = await session.scalars(
        select(ModelDefinition).order_by(
            ModelDefinition.provider_id.asc(),
            ModelDefinition.provider_model_id.asc(),
            ModelDefinition.id.asc(),
        )
    )
    return list(result)


async def upsert_model(
    session: AsyncSession,
    *,
    provider_id: str,
    provider_model_id: str,
    values: Mapping[str, Any],
) -> None:
    statement = insert(ModelDefinition).values(
        provider_id=provider_id,
        provider_model_id=provider_model_id,
        **values,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_model_definitions_provider_id_provider_model_id",
            set_={**values, "updated_at": func.now()},
        )
    )


async def mark_missing_stale(
    session: AsyncSession,
    *,
    provider_id: str,
    returned_model_ids: set[str],
) -> int:
    statement = update(ModelDefinition).where(
        ModelDefinition.provider_id == provider_id,
        ModelDefinition.status == "AVAILABLE",
    )
    if returned_model_ids:
        statement = statement.where(ModelDefinition.provider_model_id.not_in(returned_model_ids))
    result = await session.execute(statement.values(status="STALE"))
    return int(result.rowcount or 0)
