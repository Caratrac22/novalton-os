"""Trusted, deterministic resolution of a persisted Agent challenge."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents import repository as agents_repository
from novalton_api.modules.agents.schemas import AgentRunStatus
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.orchestrator import challenge_repository
from novalton_api.modules.orchestrator.models import AgentChallengeResolution
from novalton_api.modules.orchestrator.schemas import (
    ChallengeResolutionDecision,
    ChallengeResolutionRequest,
    ChallengeResolutionResponse,
    OrchestrationOutcome,
)
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import PolicyEffect, PolicyEvaluationRequest
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.runtime_events.service import append_event
from novalton_api.modules.workflows import repository as workflows_repository
from novalton_api.modules.workflows import service as workflows_service
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStepRun
from novalton_api.modules.workflows.schemas import WorkflowRunStatus, WorkflowStepRunStatus

logger = logging.getLogger(__name__)


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _conflict(message: str) -> ApplicationError:
    return ApplicationError("challenge_resolution_conflict", message, status_code=409)


async def _runtime_event(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    resolution: AgentChallengeResolution,
    event_type: str,
    reason_code: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "workflow_run_id": str(run.id),
        "workflow_status": run.status,
        "workflow_step_run_id": str(step_run.id),
        "step_status": step_run.status,
        "agent_run_id": str(resolution.agent_run_id),
        "challenge_level": resolution.challenge_level,
        "decision": resolution.decision,
        "decision_actor_type": "local_user",
    }
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if resolution.specialization_role is not None:
        payload["specialization_role"] = resolution.specialization_role
    if resolution.qa_verdict is not None:
        payload["qa_verdict"] = resolution.qa_verdict
    await append_event(
        session,
        data=RuntimeEventCreate(
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            task_id=run.task_id,
            correlation_id=run.correlation_id,
            event_type=event_type,
            source="orchestrator",
            payload=payload,
        ),
        commit=False,
    )


async def _audit(
    session: AsyncSession, *, run: WorkflowRun, resolution: AgentChallengeResolution
) -> None:
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            task_id=run.task_id,
            resource_type="task",
            resource_id=run.task_id,
            action="workflow.challenge.resolve",
            actor_type="local_user",
            actor_id=None,
            outcome="success",
            correlation_id=run.correlation_id,
            metadata={
                "resolution_id": str(resolution.id),
                "workflow_run_id": str(run.id),
                "workflow_step_run_id": str(resolution.workflow_step_run_id),
                "agent_run_id": str(resolution.agent_run_id),
                "challenge_level": resolution.challenge_level,
                "decision": resolution.decision,
                "reason_supplied": resolution.reason is not None,
            },
        ),
        commit=False,
    )


def _failure_after_acceptance(resolution: AgentChallengeResolution) -> str | None:
    if (
        resolution.specialization_role in {"developer_manager", "developer_worker"}
        and resolution.result_status != "COMPLETED"
    ):
        return f"{resolution.specialization_role}_not_completed"
    if resolution.specialization_role == "qa_worker":
        if resolution.qa_verdict == "FAIL":
            return "qa_failed"
        if resolution.qa_verdict == "INCONCLUSIVE":
            return "qa_inconclusive"
        if resolution.result_status != "COMPLETED":
            return "qa_not_completed"
    return None


async def _transition_failed(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    resolution: AgentChallengeResolution,
    reason_code: str,
) -> tuple[WorkflowRun, WorkflowStepRun, OrchestrationOutcome]:
    now = datetime.now(UTC)
    transitioned_step = await workflows_repository.transition_step_run(
        session,
        run_id=run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.RUNNING.value,
        values={
            "status": WorkflowStepRunStatus.FAILED.value,
            "failure_code": reason_code,
            "completed_at": now,
            "updated_at": now,
        },
    )
    transitioned_run = await workflows_repository.transition_run(
        session,
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        run_id=run.id,
        expected=WorkflowRunStatus.RUNNING.value,
        values={
            "status": WorkflowRunStatus.FAILED.value,
            "failure_code": reason_code,
            "completed_at": now,
            "updated_at": now,
        },
    )
    if transitioned_step is None or transitioned_run is None:
        raise _conflict("Workflow state changed during challenge resolution")
    await _runtime_event(
        session,
        run=transitioned_run,
        step_run=transitioned_step,
        resolution=resolution,
        event_type="workflow.step.failed",
        reason_code=reason_code,
    )
    await _runtime_event(
        session,
        run=transitioned_run,
        step_run=transitioned_step,
        resolution=resolution,
        event_type="workflow.run.failed",
        reason_code=reason_code,
    )
    return transitioned_run, transitioned_step, OrchestrationOutcome.WORKFLOW_FAILED


async def _transition_accepted(
    session: AsyncSession,
    *,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    resolution: AgentChallengeResolution,
) -> tuple[WorkflowRun, WorkflowStepRun, OrchestrationOutcome]:
    failure_code = _failure_after_acceptance(resolution)
    if failure_code is not None:
        return await _transition_failed(
            session,
            run=run,
            step_run=step_run,
            resolution=resolution,
            reason_code=failure_code,
        )

    now = datetime.now(UTC)
    transitioned_step = await workflows_repository.transition_step_run(
        session,
        run_id=run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.RUNNING.value,
        values={
            "status": WorkflowStepRunStatus.COMPLETED.value,
            "failure_code": None,
            "completed_at": now,
            "updated_at": now,
        },
    )
    if transitioned_step is None:
        raise _conflict("Workflow state changed during challenge resolution")
    for dependent in await workflows_repository.pending_dependents(
        session, run_id=run.id, completed_step_id=transitioned_step.workflow_step_id
    ):
        if (
            await workflows_repository.incomplete_dependency_count(
                session, run_id=run.id, step_id=dependent.workflow_step_id
            )
            == 0
        ):
            await workflows_repository.transition_step_run(
                session,
                run_id=run.id,
                step_run_id=dependent.id,
                expected=WorkflowStepRunStatus.PENDING.value,
                values={"status": WorkflowStepRunStatus.READY.value, "updated_at": now},
            )
    await _runtime_event(
        session,
        run=run,
        step_run=transitioned_step,
        resolution=resolution,
        event_type="workflow.step.completed",
    )
    counts = await workflows_repository.count_step_states(session, run_id=run.id)
    ordered = await workflows_repository.ordered_step_runs(session, run_id=run.id)
    if counts.get(WorkflowStepRunStatus.COMPLETED.value, 0) != len(ordered):
        return run, transitioned_step, OrchestrationOutcome.STEP_COMPLETED

    transitioned_run = await workflows_repository.transition_run(
        session,
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        run_id=run.id,
        expected=WorkflowRunStatus.RUNNING.value,
        values={
            "status": WorkflowRunStatus.COMPLETED.value,
            "failure_code": None,
            "completed_at": now,
            "updated_at": now,
        },
    )
    if transitioned_run is None:
        raise _conflict("Workflow state changed during challenge resolution")
    await _runtime_event(
        session,
        run=transitioned_run,
        step_run=transitioned_step,
        resolution=resolution,
        event_type="workflow.run.completed",
    )
    return transitioned_run, transitioned_step, OrchestrationOutcome.WORKFLOW_COMPLETED


def _response(
    resolution: AgentChallengeResolution,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    outcome: OrchestrationOutcome,
    reason_code: str | None,
) -> ChallengeResolutionResponse:
    assert resolution.decision is not None
    assert resolution.decision_actor_type is not None
    assert resolution.decided_at is not None
    return ChallengeResolutionResponse(
        resolution_id=resolution.id,
        workflow_run_id=run.id,
        workflow_step_run_id=step_run.id,
        agent_run_id=resolution.agent_run_id,
        challenge_level=resolution.challenge_level,
        decision=resolution.decision,
        decision_actor_type=resolution.decision_actor_type,
        decided_at=resolution.decided_at,
        workflow_status=run.status,
        step_status=step_run.status,
        outcome=outcome,
        reason_code=reason_code,
    )


async def resolve(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    workflow_step_run_id: UUID,
    data: ChallengeResolutionRequest,
) -> ChallengeResolutionResponse:
    """Resolve one challenge as the server-authenticated local V1 human."""
    try:
        resolution = await challenge_repository.get_scoped_for_update(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_run_id=workflow_run_id,
            workflow_step_run_id=workflow_step_run_id,
        )
        if resolution is None:
            raise _not_found()
        if resolution.decision is not None:
            if resolution.decision != data.decision.value or resolution.reason != data.reason:
                raise _conflict("Challenge already has a different terminal decision")
            run = await workflows_service.get_run(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=workflow_run_id,
            )
            step_run = await workflows_repository.get_step_run(
                session, run_id=run.id, step_run_id=workflow_step_run_id
            )
            if step_run is None:
                raise _not_found()
            outcome = (
                OrchestrationOutcome.WORKFLOW_COMPLETED
                if run.status == WorkflowRunStatus.COMPLETED.value
                else OrchestrationOutcome.WORKFLOW_FAILED
                if run.status == WorkflowRunStatus.FAILED.value
                else OrchestrationOutcome.STEP_COMPLETED
            )
            return _response(resolution, run, step_run, outcome, run.failure_code)

        if (
            resolution.challenge_level == "BLOCK_RECOMMENDED"
            and data.decision == ChallengeResolutionDecision.ACCEPT_RESULT
        ):
            raise _conflict("BLOCK_RECOMMENDED cannot be accepted in V1")

        run = await workflows_service.get_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=workflow_run_id,
        )
        step_run = await workflows_repository.get_step_run(
            session, run_id=run.id, step_run_id=workflow_step_run_id
        )
        agent_run = await agents_repository.get_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=resolution.agent_run_id,
        )
        ordered = await workflows_repository.ordered_step_runs(session, run_id=run.id)
        running_ids = [item.id for item, _ in ordered if item.status == "RUNNING"]
        if (
            run.status != WorkflowRunStatus.RUNNING.value
            or step_run is None
            or step_run.status != WorkflowStepRunStatus.RUNNING.value
            or step_run.agent_run_id != resolution.agent_run_id
            or agent_run is None
            or agent_run.status != AgentRunStatus.SUCCEEDED.value
            or running_ids != [step_run.id]
        ):
            raise _conflict("Challenge is not the exact active waiting step")

        policy = await policy_service.evaluate_decision(
            session,
            request=PolicyEvaluationRequest(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                action="workflow.challenge.resolve",
                actor_type="local_user",
                resource_type="task",
                resource_id=run.task_id,
                project_id=run.project_id,
                task_id=run.task_id,
            ),
        )
        if policy.effect == PolicyEffect.BLOCK:
            raise ApplicationError(
                "challenge_resolution_policy_blocked",
                "Policy blocks challenge resolution",
                status_code=409,
            )

        decided = await challenge_repository.decide_pending(
            session,
            resolution_id=resolution.id,
            decision=data.decision.value,
            reason=data.reason,
            decided_at=datetime.now(UTC),
        )
        if decided is None:
            raise _conflict("Challenge decision conflicted with another decision")
        await _audit(session, run=run, resolution=decided)
        await _runtime_event(
            session,
            run=run,
            step_run=step_run,
            resolution=decided,
            event_type="workflow.challenge.resolved",
        )

        if data.decision == ChallengeResolutionDecision.REJECT_RESULT:
            reason_code = "agent_challenge_rejected"
            run, step_run, outcome = await _transition_failed(
                session,
                run=run,
                step_run=step_run,
                resolution=decided,
                reason_code=reason_code,
            )
        else:
            reason_code = _failure_after_acceptance(decided)
            run, step_run, outcome = await _transition_accepted(
                session, run=run, step_run=step_run, resolution=decided
            )
        await session.commit()
        return _response(decided, run, step_run, outcome, reason_code)
    except ApplicationError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Challenge resolution persistence failed",
            extra={
                "event": "workflow.challenge.persistence_failed",
                "exception_type": type(exc).__name__,
            },
        )
        raise ApplicationError(
            "challenge_resolution_persistence_failed",
            "Challenge resolution could not be persisted",
            status_code=500,
        ) from None
