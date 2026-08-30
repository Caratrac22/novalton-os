"""One-step deterministic orchestration over durable workflow state."""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.errors import ProviderCancellationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import execution as agent_execution
from novalton_api.modules.agents.contracts import (
    AgentInput,
    AgentResultStatus,
    ChallengeLevel,
    ModelRequirementHints,
)
from novalton_api.modules.agents.schemas import AgentRunStatus
from novalton_api.modules.orchestrator import challenge_repository, specializations
from novalton_api.modules.orchestrator.schemas import OrchestrationOutcome, OrchestrationResult
from novalton_api.modules.qa_worker.contracts import QAVerdict, QAWorkerResult
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.runtime_events.service import append_event
from novalton_api.modules.workflows import repository
from novalton_api.modules.workflows import service as workflow_service
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStep, WorkflowStepRun
from novalton_api.modules.workflows.schemas import WorkflowRunStatus, WorkflowStepRunStatus

logger = logging.getLogger(__name__)
_MEANINGFUL_CHALLENGES = {
    ChallengeLevel.HUMAN_REVIEW_RECOMMENDED,
    ChallengeLevel.BLOCK_RECOMMENDED,
}


async def _ensure_running(session: AsyncSession, run: WorkflowRun) -> tuple[WorkflowRun, bool]:
    if run.status != WorkflowRunStatus.CREATED.value:
        return run, False
    tenant_id, workspace_id, run_id = run.tenant_id, run.workspace_id, run.id
    try:
        started = await workflow_service.start_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run_id,
        )
        return started, True
    except ApplicationError as error:
        if error.code != "workflow_run_invalid_transition":
            raise
        await session.rollback()
        current = await workflow_service.get_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run_id,
        )
        return current, False


async def _event(
    session: AsyncSession,
    run: WorkflowRun,
    event_type: str,
    *,
    step_run: WorkflowStepRun | None = None,
    step: WorkflowStep | None = None,
    agent_run_id: UUID | None = None,
    reason_code: str | None = None,
    challenge_level: ChallengeLevel | None = None,
    specialization_role: str | None = None,
    qa_verdict: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "workflow_run_id": str(run.id),
        "workflow_status": run.status,
    }
    if step_run is not None:
        payload.update(workflow_step_run_id=str(step_run.id), step_status=step_run.status)
    if step is not None:
        payload["step_key"] = step.step_key
    if agent_run_id is not None:
        payload["agent_run_id"] = str(agent_run_id)
    if reason_code is not None:
        payload["reason_code"] = reason_code
    if challenge_level is not None:
        payload["challenge_level"] = challenge_level.value
    if specialization_role is not None:
        payload["specialization_role"] = specialization_role
    if qa_verdict is not None:
        payload["qa_verdict"] = qa_verdict
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
    )


async def _result(
    session: AsyncSession,
    run: WorkflowRun,
    outcome: OrchestrationOutcome,
    *,
    step_run: WorkflowStepRun | None = None,
    step: WorkflowStep | None = None,
    agent_run_id: UUID | None = None,
    reason_code: str | None = None,
    challenge_level: ChallengeLevel | None = None,
) -> OrchestrationResult:
    counts = await repository.count_step_states(session, run_id=run.id)
    return OrchestrationResult(
        workflow_run_id=run.id,
        workflow_status=WorkflowRunStatus(run.status),
        workflow_step_run_id=step_run.id if step_run else None,
        step_key=step.step_key if step else None,
        agent_run_id=agent_run_id,
        step_status=WorkflowStepRunStatus(step_run.status) if step_run else None,
        outcome=outcome,
        reason_code=reason_code,
        challenge_level=challenge_level,
        remaining_ready=counts.get("READY", 0),
        remaining_pending=counts.get("PENDING", 0),
    )


def _agent_input(run: WorkflowRun, step: WorkflowStep) -> AgentInput:
    capabilities = [step.assigned_capability] if step.assigned_capability else []
    return AgentInput(
        objective=step.title,
        constraints=[
            "Requested actions are proposals only",
            "Do not use tools or execute external actions",
            "Remain within the assigned workflow step",
        ],
        project_id=str(run.project_id),
        task_id=str(run.task_id),
        expected_output_type="workflow.step_result",
        permitted_tools=[],
        model_requirements=ModelRequirementHints(required_capabilities=capabilities),
    )


async def _fail(
    session: AsyncSession,
    run: WorkflowRun,
    step_run: WorkflowStepRun,
    step: WorkflowStep,
    reason_code: str,
    *,
    agent_run_id: UUID | None = None,
) -> OrchestrationResult:
    step_run = await workflow_service.transition_step(
        session,
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        run_id=run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.RUNNING,
        target=WorkflowStepRunStatus.FAILED,
        failure_code=reason_code,
    )
    run = await workflow_service.fail_run(
        session,
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        run_id=run.id,
        failure_code=reason_code,
    )
    await _event(
        session,
        run,
        "workflow.step.failed",
        step_run=step_run,
        step=step,
        agent_run_id=agent_run_id,
        reason_code=reason_code,
    )
    await _event(
        session,
        run,
        "workflow.run.failed",
        step_run=step_run,
        step=step,
        agent_run_id=agent_run_id,
        reason_code=reason_code,
    )
    return await _result(
        session,
        run,
        OrchestrationOutcome.WORKFLOW_FAILED,
        step_run=step_run,
        step=step,
        agent_run_id=agent_run_id,
        reason_code=reason_code,
    )


async def advance(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
) -> OrchestrationResult:
    """Claim and process at most one READY step, with no retry or fallback."""
    run = await workflow_service.get_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=workflow_run_id
    )
    if run.status == WorkflowRunStatus.CANCELLED.value:
        return await _result(
            session, run, OrchestrationOutcome.CANCELLED, reason_code="workflow_cancelled"
        )
    if run.status == WorkflowRunStatus.COMPLETED.value:
        return await _result(
            session,
            run,
            OrchestrationOutcome.WORKFLOW_COMPLETED,
            reason_code="workflow_already_completed",
        )
    if run.status == WorkflowRunStatus.FAILED.value:
        return await _result(
            session,
            run,
            OrchestrationOutcome.WORKFLOW_FAILED,
            reason_code=run.failure_code or "workflow_failed",
        )

    ordered = await repository.ordered_step_runs(session, run_id=run.id)
    if ordered and all(step_run.status == "COMPLETED" for step_run, _ in ordered):
        run = await workflow_service.complete_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
        )
        await _event(session, run, "workflow.run.completed")
        return await _result(session, run, OrchestrationOutcome.WORKFLOW_COMPLETED)
    selected = next(
        ((step_run, step) for step_run, step in ordered if step_run.status == "READY"), None
    )
    if selected is None:
        waiting = next(
            ((value, step) for value, step in ordered if value.status == "RUNNING"), None
        )
        if waiting is not None:
            step_run, step = waiting
            resolution = await challenge_repository.get_for_step(
                session,
                workflow_run_id=run.id,
                workflow_step_run_id=step_run.id,
            )
            return await _result(
                session,
                run,
                OrchestrationOutcome.WAITING_FOR_HUMAN,
                step_run=step_run,
                step=step,
                agent_run_id=step_run.agent_run_id,
                reason_code="agent_challenge"
                if resolution is not None and resolution.decision is None
                else "step_requires_intervention",
                challenge_level=ChallengeLevel(resolution.challenge_level)
                if resolution is not None and resolution.decision is None
                else None,
            )
        return await _result(
            session, run, OrchestrationOutcome.NO_RUNNABLE_STEP, reason_code="no_ready_step"
        )
    step_run, step = selected

    if step.step_type in {"MANUAL_REVIEW", "SYSTEM"}:
        was_created = run.status == WorkflowRunStatus.CREATED.value
        run, started = await _ensure_running(session, run)
        if was_created and not started:
            return await _result(
                session,
                run,
                OrchestrationOutcome.NO_RUNNABLE_STEP,
                reason_code="workflow_start_conflict",
            )
        if started:
            await _event(session, run, "workflow.run.started")
        reason = (
            "manual_review_required"
            if step.step_type == "MANUAL_REVIEW"
            else "unsupported_system_step"
        )
        await _event(
            session,
            run,
            "workflow.run.waiting_for_human",
            step_run=step_run,
            step=step,
            reason_code=reason,
        )
        return await _result(
            session,
            run,
            OrchestrationOutcome.WAITING_FOR_HUMAN,
            step_run=step_run,
            step=step,
            reason_code=reason,
        )

    if step.step_type != "AGENT_TASK" or step.agent_definition_id is None:
        was_created = run.status == WorkflowRunStatus.CREATED.value
        run, started = await _ensure_running(session, run)
        if was_created and not started:
            return await _result(
                session,
                run,
                OrchestrationOutcome.NO_RUNNABLE_STEP,
                reason_code="workflow_start_conflict",
            )
        if started:
            await _event(session, run, "workflow.run.started")
        return await _result(
            session,
            run,
            OrchestrationOutcome.WAITING_FOR_HUMAN,
            step_run=step_run,
            step=step,
            reason_code="agent_assignment_required",
        )

    was_created = run.status == WorkflowRunStatus.CREATED.value
    run, started = await _ensure_running(session, run)
    if was_created and not started:
        return await _result(
            session,
            run,
            OrchestrationOutcome.NO_RUNNABLE_STEP,
            reason_code="workflow_start_conflict",
        )
    if started:
        await _event(session, run, "workflow.run.started")
    if run.status != WorkflowRunStatus.RUNNING.value:
        return await _result(
            session,
            run,
            OrchestrationOutcome.CANCELLED
            if run.status == WorkflowRunStatus.CANCELLED.value
            else OrchestrationOutcome.NO_RUNNABLE_STEP,
            reason_code="workflow_not_runnable",
        )
    claimed_run_id = run.id
    try:
        step_run = await workflow_service.transition_step(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=claimed_run_id,
            step_run_id=step_run.id,
            expected=WorkflowStepRunStatus.READY,
            target=WorkflowStepRunStatus.RUNNING,
        )
    except ApplicationError as error:
        if error.code != "workflow_step_invalid_transition":
            raise
        await session.rollback()
        current = await workflow_service.get_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=claimed_run_id
        )
        return await _result(
            session,
            current,
            OrchestrationOutcome.NO_RUNNABLE_STEP,
            reason_code="step_claim_conflict",
        )
    await _event(session, run, "workflow.step.started", step_run=step_run, step=step)

    specialization_role: str | None = None
    try:
        specialized = await specializations.dispatch(
            session, registry=registry, run=run, step_run=step_run, step=step
        )
        if specialized is None:
            executed = await agent_execution.execute(
                session,
                registry=registry,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                definition_id=step.agent_definition_id,
                data=_agent_input(run, step),
            )
        else:
            executed = specialized.response
            specialization_role = specialized.role
    except ApplicationError as error:
        return await _fail(session, run, step_run, step, error.code)
    except (ProviderCancellationError, asyncio.CancelledError):
        step_run = await workflow_service.transition_step(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run.id,
            step_run_id=step_run.id,
            expected=WorkflowStepRunStatus.RUNNING,
            target=WorkflowStepRunStatus.CANCELLED,
        )
        run = await workflow_service.cancel_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
        )
        return await _result(
            session,
            run,
            OrchestrationOutcome.CANCELLED,
            step_run=step_run,
            step=step,
            reason_code="agent_execution_cancelled",
        )

    step_run = await workflow_service.link_agent_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run.id,
        step_run_id=step_run.id,
        agent_run_id=executed.agent_run_id,
    )
    if executed.status != AgentRunStatus.SUCCEEDED or executed.result is None:
        return await _fail(
            session,
            run,
            step_run,
            step,
            executed.error_code or "agent_execution_failed",
            agent_run_id=executed.agent_run_id,
        )

    challenge = executed.result.challenge.level
    if challenge in _MEANINGFUL_CHALLENGES:
        if (
            specialization_role in {"developer_manager", "developer_worker"}
            and executed.result.status == AgentResultStatus.COMPLETED
        ):
            try:
                await specializations.persist_next_handoff(
                    session, run=run, step_run=step_run, result=executed.result
                )
            except ApplicationError as error:
                return await _fail(
                    session,
                    run,
                    step_run,
                    step,
                    error.code,
                    agent_run_id=executed.agent_run_id,
                )
        await challenge_repository.create_pending(
            session,
            tenant_id=run.tenant_id,
            workspace_id=run.workspace_id,
            workflow_run_id=run.id,
            workflow_step_run_id=step_run.id,
            agent_run_id=executed.agent_run_id,
            challenge_level=challenge.value,
            result_status=executed.result.status.value,
            specialization_role=specialization_role,
            qa_verdict=executed.result.verdict.value
            if isinstance(executed.result, QAWorkerResult)
            else None,
        )
        await _event(
            session,
            run,
            "workflow.run.waiting_for_human",
            step_run=step_run,
            step=step,
            agent_run_id=executed.agent_run_id,
            reason_code="agent_challenge",
            challenge_level=challenge,
            specialization_role=specialization_role,
        )
        await session.commit()
        return await _result(
            session,
            run,
            OrchestrationOutcome.WAITING_FOR_HUMAN,
            step_run=step_run,
            step=step,
            agent_run_id=executed.agent_run_id,
            reason_code="agent_challenge",
            challenge_level=challenge,
        )

    if (
        specialization_role in {"developer_manager", "developer_worker"}
        and executed.result.status != AgentResultStatus.COMPLETED
    ):
        return await _fail(
            session,
            run,
            step_run,
            step,
            f"{specialization_role}_not_completed",
            agent_run_id=executed.agent_run_id,
        )
    if isinstance(executed.result, QAWorkerResult):
        if executed.result.verdict == QAVerdict.FAIL:
            return await _fail(
                session, run, step_run, step, "qa_failed", agent_run_id=executed.agent_run_id
            )
        if executed.result.verdict == QAVerdict.INCONCLUSIVE:
            return await _fail(
                session, run, step_run, step, "qa_inconclusive", agent_run_id=executed.agent_run_id
            )
        if executed.result.status != AgentResultStatus.COMPLETED:
            return await _fail(
                session, run, step_run, step, "qa_not_completed", agent_run_id=executed.agent_run_id
            )

    if specialization_role in {"developer_manager", "developer_worker"}:
        try:
            await specializations.persist_next_handoff(
                session, run=run, step_run=step_run, result=executed.result
            )
        except ApplicationError as error:
            return await _fail(
                session, run, step_run, step, error.code, agent_run_id=executed.agent_run_id
            )

    step_run = await workflow_service.transition_step(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.RUNNING,
        target=WorkflowStepRunStatus.COMPLETED,
    )
    await _event(
        session,
        run,
        "workflow.step.completed",
        step_run=step_run,
        step=step,
        agent_run_id=executed.agent_run_id,
        challenge_level=challenge if challenge != ChallengeLevel.NONE else None,
        specialization_role=specialization_role,
        qa_verdict=executed.result.verdict.value
        if isinstance(executed.result, QAWorkerResult)
        else None,
    )
    counts = await repository.count_step_states(session, run_id=run.id)
    if counts.get("COMPLETED", 0) == len(ordered):
        run = await workflow_service.complete_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run.id
        )
        await _event(
            session,
            run,
            "workflow.run.completed",
            step_run=step_run,
            step=step,
            agent_run_id=executed.agent_run_id,
        )
        outcome = OrchestrationOutcome.WORKFLOW_COMPLETED
    else:
        outcome = OrchestrationOutcome.STEP_COMPLETED
    logger.info(
        "Orchestration cycle completed",
        extra={
            "event": "orchestrator.advance.completed",
            "workflow_run_id": str(run.id),
            "agent_run_id": str(executed.agent_run_id),
            "status": run.status,
            "outcome_class": outcome.value,
        },
    )
    return await _result(
        session,
        run,
        outcome,
        step_run=step_run,
        step=step,
        agent_run_id=executed.agent_run_id,
        challenge_level=challenge if challenge != ChallengeLevel.NONE else None,
    )
