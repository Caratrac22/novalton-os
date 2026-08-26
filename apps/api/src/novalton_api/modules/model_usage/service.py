"""Trusted model-run lifecycle and usage capture."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import GenerationResult
from novalton_api.infrastructure.providers.errors import ProviderFailure
from novalton_api.modules.model_catalog.repository import get_model
from novalton_api.modules.model_usage import repository
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.model_usage.schemas import ModelRunStart, ModelRunStatus
from novalton_api.modules.projects.repository import get_project
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")
_MILLION = Decimal(1_000_000)
_MAX_TOKEN_COUNT = 1_000_000_000_000
_MAX_MONEY = Decimal("9999999999.9999999999")


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


async def _require_scope(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, project_id: UUID | None = None
) -> None:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise _not_found()
    if (
        project_id is not None
        and await get_project(session, workspace_id=workspace_id, project_id=project_id) is None
    ):
        raise _not_found()


async def start_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: ModelRunStart
) -> ModelRun:
    await _require_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=data.project_id
    )
    model = (
        await get_model(session, model_id=data.model_definition_id)
        if data.model_definition_id
        else None
    )
    if data.model_definition_id is not None and model is None:
        raise _not_found()
    provider_id = model.provider_id if model is not None else data.provider_id
    provider_model_id = model.provider_model_id if model is not None else data.provider_model_id
    if provider_id is None or provider_model_id is None:
        raise _not_found()
    if (
        data.currency is not None
        and model is not None
        and model.currency is not None
        and data.currency != model.currency
    ):
        raise ApplicationError(
            "model_run_currency_mismatch", "Cost currency does not match model pricing"
        )
    now = datetime.now(UTC)
    currency = data.currency or (model.currency if model is not None else None)
    run = await repository.create_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=data.project_id,
        agent_run_id=data.agent_run_id,
        model_definition_id=model.id if model is not None else None,
        provider_id=provider_id,
        provider_model_id=provider_model_id,
        status=ModelRunStatus.RUNNING.value,
        correlation_id=get_correlation_id(),
        estimated_cost=data.estimated_cost,
        input_price_per_million_snapshot=(
            model.input_price_per_million if model is not None else None
        ),
        output_price_per_million_snapshot=(
            model.output_price_per_million if model is not None else None
        ),
        currency=currency,
        started_at=now,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def _require_running(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, model_run_id: UUID
) -> ModelRun:
    await _require_scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    run = await repository.get_scoped_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, model_run_id=model_run_id
    )
    if run is None:
        raise _not_found()
    if run.status != ModelRunStatus.RUNNING.value:
        raise ApplicationError(
            "model_run_terminal", "Model run is already terminal", status_code=409
        )
    return run


def _actual_cost(run: ModelRun, result: GenerationResult) -> Decimal | None:
    if result.input_tokens is None or result.output_tokens is None:
        return None
    if (
        run.input_price_per_million_snapshot is None
        or run.output_price_per_million_snapshot is None
    ):
        return None
    cost = (
        (
            Decimal(result.input_tokens) * run.input_price_per_million_snapshot
            + Decimal(result.output_tokens) * run.output_price_per_million_snapshot
        )
        / _MILLION
    ).quantize(Decimal("0.0000000001"))
    if cost > _MAX_MONEY:
        raise ApplicationError("model_run_invalid_usage", "Calculated provider cost is invalid")
    return cost


async def mark_succeeded(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    model_run_id: UUID,
    result: GenerationResult,
) -> ModelRun:
    run = await _require_running(
        session, tenant_id=tenant_id, workspace_id=workspace_id, model_run_id=model_run_id
    )
    if (result.provider_id, result.model_id) != (run.provider_id, run.provider_model_id):
        raise ApplicationError(
            "model_run_identity_mismatch", "Provider result identity does not match model run"
        )
    if (
        result.provider_request_id is not None
        and _SAFE_REQUEST_ID.fullmatch(result.provider_request_id) is None
    ):
        raise ApplicationError(
            "model_run_invalid_request_id", "Provider request identifier is invalid"
        )
    if result.duration_ms is not None and result.duration_ms > 86_400_000:
        raise ApplicationError("model_run_invalid_duration", "Provider duration is invalid")
    if any(
        value is not None and value > _MAX_TOKEN_COUNT
        for value in (result.input_tokens, result.output_tokens, result.total_tokens)
    ):
        raise ApplicationError("model_run_invalid_usage", "Provider token usage is invalid")
    if (
        result.total_tokens is not None
        and result.input_tokens is not None
        and result.output_tokens is not None
        and result.total_tokens != result.input_tokens + result.output_tokens
    ):
        raise ApplicationError("model_run_invalid_usage", "Provider token usage is inconsistent")
    total = result.total_tokens
    if total is None and result.input_tokens is not None and result.output_tokens is not None:
        total = result.input_tokens + result.output_tokens
    completed_at = datetime.now(UTC)
    updated = await repository.transition_running(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        model_run_id=model_run_id,
        values={
            "status": ModelRunStatus.SUCCEEDED.value,
            "provider_request_id": result.provider_request_id,
            "provider_resolved_model_id": result.provider_resolved_model_id,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": total,
            "actual_cost": _actual_cost(run, result),
            "duration_ms": Decimal(str(result.duration_ms))
            if result.duration_ms is not None
            else None,
            "completed_at": completed_at,
            "updated_at": completed_at,
        },
    )
    if updated is None:
        raise ApplicationError(
            "model_run_terminal", "Model run is already terminal", status_code=409
        )
    await session.commit()
    return updated


async def mark_failed(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    model_run_id: UUID,
    failure: ProviderFailure,
) -> ModelRun:
    status = (
        ModelRunStatus.CANCELLED
        if failure == ProviderFailure.CANCELLATION
        else ModelRunStatus.FAILED
    )
    completed_at = datetime.now(UTC)
    await _require_running(
        session, tenant_id=tenant_id, workspace_id=workspace_id, model_run_id=model_run_id
    )
    updated = await repository.transition_running(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        model_run_id=model_run_id,
        values={
            "status": status.value,
            "failure_code": failure.value,
            "completed_at": completed_at,
            "updated_at": completed_at,
        },
    )
    if updated is None:
        raise ApplicationError(
            "model_run_terminal", "Model run is already terminal", status_code=409
        )
    await session.commit()
    return updated


async def cancel_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, model_run_id: UUID
) -> ModelRun:
    return await mark_failed(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        model_run_id=model_run_id,
        failure=ProviderFailure.CANCELLATION,
    )


async def get_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, model_run_id: UUID
) -> ModelRun:
    await _require_scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    run = await repository.get_scoped_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, model_run_id=model_run_id
    )
    if run is None:
        raise _not_found()
    return run


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: ModelRunStatus | None,
) -> list[ModelRun]:
    await _require_scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await repository.list_scoped_runs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=status.value if status else None,
    )
