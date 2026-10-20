"""Fail abandoned initial step claims without guessing or replaying an AgentRun."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.workflows import repository
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStep, WorkflowStepRun

_INITIAL_STEP_LEASE = timedelta(hours=1)
_INTERRUPTED = "initial_step_interrupted"


async def reconcile_stale_unlinked_step(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Reclaim only an aged AGENT_TASK claim that still has no linked AgentRun.

    Row locking serializes with AgentRun linkage; a late producer cannot link
    after the terminal transition. Orphan AgentRuns are never inferred by task
    or timestamp, started, cancelled, or reassigned to this workflow.
    """
    instant = now or datetime.now(UTC)
    step = await session.scalar(
        select(WorkflowStepRun)
        .join(WorkflowRun, WorkflowRun.id == WorkflowStepRun.workflow_run_id)
        .join(WorkflowStep, WorkflowStep.id == WorkflowStepRun.workflow_step_id)
        .where(
            WorkflowRun.id == workflow_run_id,
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
            WorkflowRun.status == "RUNNING",
            WorkflowStep.step_type == "AGENT_TASK",
            WorkflowStepRun.status == "RUNNING",
            WorkflowStepRun.agent_run_id.is_(None),
            WorkflowStepRun.started_at <= instant - _INITIAL_STEP_LEASE,
        )
        .order_by(WorkflowStepRun.id)
        .limit(1)
        .with_for_update(of=WorkflowStepRun)
        .execution_options(populate_existing=True)
    )
    if step is None:
        return False
    failed_step = await repository.transition_step_run(
        session,
        run_id=workflow_run_id,
        step_run_id=step.id,
        expected="RUNNING",
        values={
            "status": "FAILED",
            "failure_code": _INTERRUPTED,
            "completed_at": instant,
            "updated_at": instant,
        },
    )
    failed_run = await repository.transition_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=workflow_run_id,
        expected="RUNNING",
        values={
            "status": "FAILED",
            "failure_code": _INTERRUPTED,
            "completed_at": instant,
            "updated_at": instant,
        },
    )
    if failed_step is None or failed_run is None:
        await session.rollback()
        return False
    await session.commit()
    return True
