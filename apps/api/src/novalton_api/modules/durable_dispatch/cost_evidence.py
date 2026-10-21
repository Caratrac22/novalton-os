"""Bounded cost observations; estimates never claim an enforceable spend ceiling."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.models import TaskDispatch
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.model_usage.models import ModelRun, ProviderCostObservation
from novalton_api.modules.workflows.models import WorkflowStepRun


@dataclass(frozen=True)
class CostExposure:
    model_run_id: UUID
    model_definition_id: UUID | None
    status: str
    classification: str
    estimated_cost: Decimal | None
    catalog_priced_usage: Decimal | None
    reserved_estimated_exposure: Decimal | None
    price_verified_at_snapshot: datetime | None
    input_price_per_million_snapshot: Decimal | None
    output_price_per_million_snapshot: Decimal | None
    currency: str | None
    provider_generation_id: str | None
    provider_reported_cost: Decimal | None
    provider_reported_at: datetime | None


def _classification(run: ModelRun) -> str:
    if run.status == "RUNNING":
        return "EXTERNAL_OUTCOME_UNKNOWN"
    if run.status != "SUCCEEDED":
        return "EXTERNAL_COST_UNCERTAIN"
    if (
        run.provider_resolved_model_id is not None
        and run.provider_resolved_model_id != run.provider_model_id
    ):
        return "CATALOG_MODEL_MISMATCH_COST_UNCERTAIN"
    if run.actual_cost is None:
        return "CATALOG_PRICED_USAGE_UNKNOWN"
    if (
        run.reserved_estimated_exposure is not None
        and run.actual_cost > run.reserved_estimated_exposure
    ):
        return "RESERVED_ESTIMATE_EXCEEDED"
    if run.estimated_cost is None:
        return "CATALOG_PRICED_UNESTIMATED"
    if run.actual_cost > run.estimated_cost:
        return "CATALOG_ESTIMATE_EXCEEDED"
    return "CATALOG_PRICED_USAGE"


async def list_cost_exposure(
    session: AsyncSession,
    *,
    operator: OperatorAuthority,
    tenant_id: UUID,
    workspace_id: UUID,
    dispatch_id: UUID,
) -> list[CostExposure]:
    """Show actual and uncertain provider evidence for one authorized dispatch.

    A FAILED/CANCELLED invocation can still have been billed externally; no
    missing result is interpreted as zero cost. The 128-row bound matches the
    dispatch model-call ceiling and cannot expose another workspace's run.
    """
    await operator.require_human(
        session, "dispatch.read", tenant_id=tenant_id, workspace_id=workspace_id
    )
    workflow_id = await session.scalar(
        select(TaskDispatch.workflow_run_id).where(
            TaskDispatch.id == dispatch_id,
            TaskDispatch.tenant_id == tenant_id,
            TaskDispatch.workspace_id == workspace_id,
        )
    )
    if workflow_id is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    runs = list(
        await session.scalars(
            select(ModelRun)
            .join(WorkflowStepRun, WorkflowStepRun.agent_run_id == ModelRun.agent_run_id)
            .where(
                WorkflowStepRun.workflow_run_id == workflow_id,
                ModelRun.tenant_id == tenant_id,
                ModelRun.workspace_id == workspace_id,
            )
            .order_by(ModelRun.created_at, ModelRun.id)
            .limit(128)
        )
    )
    observations = {
        item.model_run_id: item
        for item in await session.scalars(
            select(ProviderCostObservation).where(
                ProviderCostObservation.model_run_id.in_([run.id for run in runs])
            )
        )
    }
    return [
        CostExposure(
            model_run_id=run.id,
            model_definition_id=run.model_definition_id,
            status=run.status,
            classification=_classification(run),
            estimated_cost=run.estimated_cost,
            catalog_priced_usage=run.actual_cost,
            reserved_estimated_exposure=run.reserved_estimated_exposure,
            price_verified_at_snapshot=run.price_verified_at_snapshot,
            input_price_per_million_snapshot=run.input_price_per_million_snapshot,
            output_price_per_million_snapshot=run.output_price_per_million_snapshot,
            currency=run.currency,
            provider_generation_id=run.provider_generation_id,
            provider_reported_cost=observations[run.id].reported_cost
            if run.id in observations
            else None,
            provider_reported_at=observations[run.id].observed_at
            if run.id in observations
            else None,
        )
        for run in runs
    ]
