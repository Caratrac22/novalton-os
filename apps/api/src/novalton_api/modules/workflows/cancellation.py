"""Durable cancellation fences; in-flight provider/tool evidence remains truthful."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents.models import AgentRun
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStepRun


async def lock_workflow(session: AsyncSession, workflow_run_id: UUID) -> None:
    """Serialize short authority reservations and cancellation, never provider I/O."""
    key = int.from_bytes(workflow_run_id.bytes[:8], byteorder="big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def require_active_workflow(
    session: AsyncSession, workflow_run_id: UUID, *, allow_created: bool = False
) -> None:
    await lock_workflow(session, workflow_run_id)
    status = await session.scalar(
        select(WorkflowRun.status).where(WorkflowRun.id == workflow_run_id)
    )
    if status == "CANCELLED":
        raise ApplicationError(
            "workflow_execution_cancelled", "Workflow execution was cancelled", status_code=409
        )
    allowed = {"CREATED", "RUNNING"} if allow_created else {"RUNNING"}
    if status not in allowed:
        raise ApplicationError(
            "workflow_execution_inactive", "Workflow execution is not active", status_code=409
        )
    from novalton_api.modules.durable_dispatch.authority import require_workflow

    await require_workflow(session, workflow_run_id)


async def require_agent_workflow(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_run_id: UUID,
    reserve_effect: bool = False,
) -> None:
    """Fence linked workflows without changing standalone AgentRun behavior."""
    agent = await session.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.id == agent_run_id,
            AgentRun.tenant_id == tenant_id,
            AgentRun.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if agent is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    rows = (
        await session.execute(
            select(WorkflowRun.id, WorkflowRun.tenant_id, WorkflowRun.workspace_id)
            .join(WorkflowStepRun, WorkflowStepRun.workflow_run_id == WorkflowRun.id)
            .where(WorkflowStepRun.agent_run_id == agent_run_id)
            .order_by(WorkflowRun.id)
        )
    ).all()
    for run_id, run_tenant, run_workspace in rows:
        if (run_tenant, run_workspace) != (tenant_id, workspace_id):
            raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
        await require_active_workflow(session, run_id)
        if reserve_effect:
            from novalton_api.modules.durable_dispatch.authority import require_effect_capacity

            await require_effect_capacity(session, run_id)


async def settle_cancelled_steps(session: AsyncSession, workflow_run_id: UUID) -> None:
    """Restart-safe projection after the authoritative cancellation commit.

    Never mark ModelRuns or RUNNING ToolCalls cancelled: the external operation
    may still finish, incur cost, or already have applied its approved effect.
    """
    cancelled = (
        select(WorkflowRun.id)
        .where(WorkflowRun.id == workflow_run_id, WorkflowRun.status == "CANCELLED")
        .exists()
    )
    instant = datetime.now(UTC)
    await session.execute(
        update(WorkflowStepRun)
        .where(
            WorkflowStepRun.workflow_run_id == workflow_run_id,
            WorkflowStepRun.status.in_(["PENDING", "READY", "RUNNING", "WAITING_FOR_APPROVAL"]),
            cancelled,
        )
        .values(status="CANCELLED", failure_code=None, completed_at=instant, updated_at=instant)
    )
    await session.commit()
