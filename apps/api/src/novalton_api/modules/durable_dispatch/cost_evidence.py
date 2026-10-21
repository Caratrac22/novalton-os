"""Bounded cost observations; estimates never claim an enforceable spend ceiling."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.models import TaskDispatch
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.workflows.models import WorkflowStepRun


@dataclass(frozen=True)
class CostExposure:
    model_run_id: UUID
    status: str
    classification: str
    estimated_cost: Decimal | None
    observed_cost: Decimal | None
    currency: str | None


def _classification(run: ModelRun) -> str:
    if run.status == "RUNNING":
        return "EXTERNAL_OUTCOME_UNKNOWN"
    if run.status != "SUCCEEDED":
        return "EXTERNAL_COST_UNCERTAIN"
    if run.actual_cost is None:
        return "ACTUAL_COST_UNKNOWN"
    if run.estimated_cost is None:
        return "RECONCILED_UNESTIMATED"
    if run.actual_cost > run.estimated_cost:
        return "ESTIMATE_EXCEEDED"
    return "RECONCILED"


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
    return [
        CostExposure(
            model_run_id=run.id,
            status=run.status,
            classification=_classification(run),
            estimated_cost=run.estimated_cost,
            observed_cost=run.actual_cost,
            currency=run.currency,
        )
        for run in runs
    ]
