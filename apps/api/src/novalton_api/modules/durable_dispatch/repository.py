"""Short PostgreSQL claims, recovery and generation/owner compare-and-set."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from novalton_api.modules.durable_dispatch.authority import (
    DispatchClaim,
    database_now,
    denied,
)
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchAttempt,
    DispatchDependency,
    TaskDispatch,
)
from novalton_api.modules.orchestrator.models import AgentChallengeResolution
from novalton_api.modules.orchestrator.schemas import OrchestrationResult
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStep, WorkflowStepRun


async def activation(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, exclusive: bool = False
) -> DispatchActivation | None:
    return await session.scalar(
        select(DispatchActivation)
        .where(
            DispatchActivation.tenant_id == tenant_id,
            DispatchActivation.workspace_id == workspace_id,
        )
        .with_for_update(read=not exclusive)
        .execution_options(populate_existing=True)
    )


async def _workflow_status(session: AsyncSession, row: TaskDispatch) -> str | None:
    return await session.scalar(
        select(WorkflowRun.status).where(
            WorkflowRun.id == row.workflow_run_id,
            WorkflowRun.tenant_id == row.tenant_id,
            WorkflowRun.workspace_id == row.workspace_id,
            WorkflowRun.project_id == row.project_id,
            WorkflowRun.task_id == row.task_id,
        )
    )


def _terminal(status: str | None) -> tuple[str, str] | None:
    return {
        "COMPLETED": ("DONE", "workflow_completed"),
        "CANCELLED": ("CANCELLED", "workflow_cancelled"),
        "FAILED": ("BLOCKED", "workflow_failed"),
        None: ("BLOCKED", "dispatch_scope_mismatch"),
    }.get(status)


def _budget(row: TaskDispatch, now) -> str | None:
    if row.deadline <= now:
        return "dispatch_deadline_exhausted"
    if row.attempt_count >= row.max_attempts:
        return "dispatch_attempt_budget_exhausted"
    if row.model_call_count >= row.max_model_calls:
        return "dispatch_model_budget_exhausted"
    return None


async def _close(
    session: AsyncSession,
    row: TaskDispatch,
    status: str,
    reason: str,
    *,
    post_status: str | None,
    step_run_id: UUID | None = None,
) -> None:
    now = await database_now(session)
    if row.status == "LEASED":
        await session.execute(
            update(DispatchAttempt)
            .where(
                DispatchAttempt.dispatch_id == row.id,
                DispatchAttempt.generation == row.generation,
                DispatchAttempt.owner == row.owner,
                DispatchAttempt.outcome.is_(None),
            )
            .values(
                outcome=status,
                reason_code=reason,
                post_status=post_status,
                workflow_step_run_id=(
                    step_run_id if step_run_id is not None else DispatchAttempt.workflow_step_run_id
                ),
                completed_at=now,
            )
        )
    row.status = status
    row.stop_reason = reason
    row.owner = None
    row.lease_expires_at = None
    row.updated_at = now


async def _pending_work(session: AsyncSession, row: TaskDispatch) -> tuple[bool, bool, bool]:
    states = list(
        await session.scalars(
            select(WorkflowStepRun.status).where(
                WorkflowStepRun.workflow_run_id == row.workflow_run_id
            )
        )
    )
    challenge = await session.scalar(
        select(AgentChallengeResolution.id)
        .where(
            AgentChallengeResolution.workflow_run_id == row.workflow_run_id,
            AgentChallengeResolution.decision.is_(None),
        )
        .limit(1)
    )
    waiting = "WAITING_FOR_APPROVAL" in states or challenge is not None
    return waiting, "RUNNING" in states, "READY" in states


async def reconcile(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, limit: int = 32
) -> int:
    """Observe existing decisions and expire uncertain claims; never call a producer."""
    configured = await activation(session, tenant_id=tenant_id, workspace_id=workspace_id)
    rows = list(
        await session.scalars(
            select(TaskDispatch)
            .where(
                TaskDispatch.tenant_id == tenant_id,
                TaskDispatch.workspace_id == workspace_id,
                TaskDispatch.status.in_(["LEASED", "WAITING_HUMAN", "READY", "BLOCKED"]),
            )
            .order_by(TaskDispatch.updated_at, TaskDispatch.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    changed = 0
    for row in rows:
        status = await _workflow_status(session, row)
        terminal = _terminal(status)
        # Rotate bounded observation across the queue; an unresolved old row
        # must not starve lease recovery or a later human decision.
        row.updated_at = await database_now(session)
        if terminal is not None:
            if (row.status, row.stop_reason) != terminal:
                await _close(session, row, *terminal, post_status=status)
                changed += 1
            continue
        now = await database_now(session)
        if row.status == "LEASED":
            reason = None
            if row.lease_expires_at <= now:
                reason = "dispatch_lease_expired"
            elif (
                configured is None
                or not configured.enabled
                or configured.generation != row.activation_generation
            ):
                reason = "dispatch_activation_revoked"
            elif row.deadline <= now:
                reason = "dispatch_deadline_exhausted"
            if reason:
                await _close(session, row, "BLOCKED", reason, post_status=status)
                changed += 1
        elif row.status in {"READY", "WAITING_HUMAN"}:
            reason = _budget(row, now)
            if reason:
                await _close(session, row, "BLOCKED", reason, post_status=status)
                changed += 1
                continue
            prerequisite = aliased(TaskDispatch)
            failed_dependency = await session.scalar(
                select(DispatchDependency.prerequisite_id)
                .join(prerequisite, prerequisite.id == DispatchDependency.prerequisite_id)
                .where(
                    DispatchDependency.dispatch_id == row.id,
                    prerequisite.status.in_(["BLOCKED", "CANCELLED"]),
                )
                .limit(1)
            )
            if failed_dependency is not None:
                await _close(
                    session, row, "BLOCKED", "dispatch_dependency_blocked", post_status=status
                )
                changed += 1
                continue
            if row.status == "WAITING_HUMAN":
                waiting, running, ready = await _pending_work(session, row)
                runnable = await session.scalar(
                    select(WorkflowStepRun.id)
                    .join(WorkflowStep, WorkflowStep.id == WorkflowStepRun.workflow_step_id)
                    .where(
                        WorkflowStepRun.workflow_run_id == row.workflow_run_id,
                        WorkflowStepRun.status == "READY",
                        WorkflowStep.step_type == "AGENT_TASK",
                        WorkflowStep.agent_definition_id.is_not(None),
                    )
                    .limit(1)
                )
                if not waiting and not running and ready and runnable is not None:
                    await _close(
                        session,
                        row,
                        "READY",
                        "dispatch_human_decision_observed",
                        post_status=status,
                    )
                    changed += 1
    await session.commit()
    return changed


async def claim(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    owner: UUID,
    lease_seconds: int = 3600,
) -> DispatchClaim | None:
    if not 60 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 60 and 3600")
    configured = await activation(session, tenant_id=tenant_id, workspace_id=workspace_id)
    if configured is None or not configured.enabled:
        await session.rollback()
        raise denied("dispatch_disabled")
    prerequisite = aliased(TaskDispatch)
    prerequisite_workflow = aliased(WorkflowRun)
    unmet = (
        select(DispatchDependency.dispatch_id)
        .join(prerequisite, prerequisite.id == DispatchDependency.prerequisite_id)
        .join(prerequisite_workflow, prerequisite_workflow.id == prerequisite.workflow_run_id)
        .where(
            DispatchDependency.dispatch_id == TaskDispatch.id,
            or_(prerequisite.status != "DONE", prerequisite_workflow.status != "COMPLETED"),
        )
        .exists()
    )
    for _ in range(32):
        now = await database_now(session)
        row = await session.scalar(
            select(TaskDispatch)
            .where(
                TaskDispatch.tenant_id == tenant_id,
                TaskDispatch.workspace_id == workspace_id,
                TaskDispatch.status == "READY",
                TaskDispatch.eligible_at <= now,
                ~unmet,
            )
            .order_by(TaskDispatch.priority.desc(), TaskDispatch.eligible_at, TaskDispatch.id)
            .limit(1)
            .with_for_update(skip_locked=True, of=TaskDispatch)
            .execution_options(populate_existing=True)
        )
        if row is None:
            await session.commit()
            return None
        status = await _workflow_status(session, row)
        terminal = _terminal(status)
        reason = _budget(row, now)
        if terminal is not None or reason is not None:
            target, reason = terminal or ("BLOCKED", reason)
            await _close(session, row, target, reason, post_status=status)
            await session.flush()
            continue
        waiting, running, _ = await _pending_work(session, row)
        if waiting or running:
            await _close(
                session,
                row,
                "WAITING_HUMAN" if waiting else "BLOCKED",
                "dispatch_human_required" if waiting else "dispatch_existing_execution",
                post_status=status,
            )
            await session.flush()
            continue
        row.generation += 1
        row.attempt_count += 1
        row.status = "LEASED"
        row.owner = owner
        row.activation_generation = configured.generation
        row.lease_expires_at = min(now + timedelta(seconds=lease_seconds), row.deadline)
        row.stop_reason = None
        row.updated_at = now
        session.add(
            DispatchAttempt(
                dispatch_id=row.id,
                workflow_run_id=row.workflow_run_id,
                generation=row.generation,
                owner=owner,
                started_at=now,
                pre_status=status,
            )
        )
        result = DispatchClaim(
            row.id,
            tenant_id,
            workspace_id,
            row.workflow_run_id,
            owner,
            row.generation,
            configured.generation,
        )
        await session.commit()
        return result
    await session.commit()
    return None


async def heartbeat(
    session: AsyncSession, claimed: DispatchClaim, *, lease_seconds: int = 3600
) -> bool:
    if not 60 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 60 and 3600")
    configured = await activation(
        session, tenant_id=claimed.tenant_id, workspace_id=claimed.workspace_id
    )
    row = await session.scalar(
        select(TaskDispatch)
        .where(
            TaskDispatch.id == claimed.dispatch_id,
            TaskDispatch.tenant_id == claimed.tenant_id,
            TaskDispatch.workspace_id == claimed.workspace_id,
            TaskDispatch.workflow_run_id == claimed.workflow_run_id,
            TaskDispatch.status == "LEASED",
            TaskDispatch.owner == claimed.owner,
            TaskDispatch.generation == claimed.generation,
            TaskDispatch.activation_generation == claimed.activation_generation,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Read database time AFTER any row-lock wait. A timestamp captured before
    # waiting could resurrect a lease which expired while the lock was held.
    now = await database_now(session)
    if (
        row is None
        or row.lease_expires_at <= now
        or row.deadline <= now
        or configured is None
        or not configured.enabled
        or configured.generation != claimed.activation_generation
    ):
        await session.rollback()
        return False
    row.lease_expires_at = min(
        max(row.lease_expires_at, now + timedelta(seconds=lease_seconds)), row.deadline
    )
    row.updated_at = now
    await session.commit()
    return True


async def finish(
    session: AsyncSession,
    claimed: DispatchClaim,
    *,
    result: OrchestrationResult | None = None,
) -> bool:
    configured = await activation(
        session, tenant_id=claimed.tenant_id, workspace_id=claimed.workspace_id
    )
    row = await session.scalar(
        select(TaskDispatch)
        .where(
            TaskDispatch.id == claimed.dispatch_id,
            TaskDispatch.tenant_id == claimed.tenant_id,
            TaskDispatch.workspace_id == claimed.workspace_id,
            TaskDispatch.workflow_run_id == claimed.workflow_run_id,
            TaskDispatch.status == "LEASED",
            TaskDispatch.owner == claimed.owner,
            TaskDispatch.generation == claimed.generation,
            TaskDispatch.activation_generation == claimed.activation_generation,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    now = await database_now(session)
    if (
        row is None
        or row.lease_expires_at <= now
        or configured is None
        or not configured.enabled
        or configured.generation != claimed.activation_generation
    ):
        await session.rollback()
        return False
    status = await _workflow_status(session, row)
    target = _terminal(status)
    step_id = None
    if result is not None and result.workflow_run_id != row.workflow_run_id:
        target = ("BLOCKED", "dispatch_result_scope_mismatch")
    elif result is not None and result.workflow_step_run_id is not None:
        step_id = await session.scalar(
            select(WorkflowStepRun.id).where(
                WorkflowStepRun.id == result.workflow_step_run_id,
                WorkflowStepRun.workflow_run_id == row.workflow_run_id,
            )
        )
        if step_id is None:
            target = ("BLOCKED", "dispatch_result_scope_mismatch")
        recorded_step = await session.scalar(
            select(DispatchAttempt.workflow_step_run_id).where(
                DispatchAttempt.dispatch_id == row.id,
                DispatchAttempt.generation == claimed.generation,
                DispatchAttempt.owner == claimed.owner,
            )
        )
        if recorded_step is not None and recorded_step != step_id:
            target = ("BLOCKED", "dispatch_result_state_mismatch")
            step_id = None
    if target is None and result is not None and result.workflow_status.value != status:
        target = ("BLOCKED", "dispatch_result_state_mismatch")
    if target is None:
        if result is None:
            target = ("BLOCKED", "dispatch_execution_interrupted")
        else:
            waiting, running, ready = await _pending_work(session, row)
            if waiting or (
                result.outcome.value == "WAITING_FOR_HUMAN"
                and result.reason_code
                in {
                    "agent_challenge",
                    "manual_review_required",
                    "unsupported_system_step",
                    "agent_assignment_required",
                }
            ):
                target = ("WAITING_HUMAN", "dispatch_human_required")
            elif running:
                target = ("BLOCKED", "dispatch_existing_execution")
            elif ready:
                reason = _budget(row, now)
                target = ("BLOCKED", reason) if reason else ("READY", "dispatch_step_completed")
            else:
                target = ("BLOCKED", "dispatch_no_runnable_step")
    await _close(session, row, *target, post_status=status, step_run_id=step_id)
    await session.commit()
    return True
