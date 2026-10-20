"""Backend-authoritative approval resolution for one prepared workspace mutation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import repository as agent_repository
from novalton_api.modules.agents import service as agent_service
from novalton_api.modules.agents.schemas import AgentRunStatus
from novalton_api.modules.approvals import service as approval_service
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.model_usage import repository as model_repository
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.orchestrator import specializations
from novalton_api.modules.tools import repository as tool_repository
from novalton_api.modules.tools import service as tool_service
from novalton_api.modules.tools.contracts import ToolExecutionStatus
from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot
from novalton_api.modules.workflows import repository as workflow_repository
from novalton_api.modules.workflows import service as workflow_service
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStepRun
from novalton_api.modules.workflows.schemas import WorkflowStepRunStatus

# A continuation can make multiple provider calls (each allowed a bounded read
# timeout), so a competing request must not terminalize a legitimate slow run.
_CONTINUATION_LEASE = timedelta(hours=1)
_INTERRUPTED = "tool_continuation_interrupted"


async def reconcile_stale_continuation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Fail an abandoned continuation; never replay provider or mutation.

    Only a claim beyond the fixed lease can be reconciled. The whole terminal
    transition commits atomically and CAS guards concurrent normal completion.
    """
    from novalton_api.modules.agents.models import AgentRun
    from novalton_api.modules.tools.models import ToolCall

    instant = now or datetime.now(UTC)
    steps = list(
        await session.scalars(
            select(WorkflowStepRun).where(
                WorkflowStepRun.workflow_run_id == workflow_run_id,
                WorkflowStepRun.status.in_(["RUNNING", "WAITING_FOR_APPROVAL"]),
            )
        )
    )
    for step in steps:
        if step.agent_run_id is None:
            continue
        agent = await session.scalar(
            select(AgentRun).where(
                AgentRun.id == step.agent_run_id,
                AgentRun.tenant_id == tenant_id,
                AgentRun.workspace_id == workspace_id,
            )
        )
        if agent is None or agent.status not in {
            "RUNNING",
            "WAITING_FOR_APPROVAL",
            "SUCCEEDED",
            "FAILED",
        }:
            continue
        calls = list(
            await session.scalars(
                select(ToolCall)
                .where(
                    ToolCall.agent_run_id == agent.id,
                    ToolCall.tenant_id == tenant_id,
                    ToolCall.workspace_id == workspace_id,
                )
                .order_by(ToolCall.created_at.desc(), ToolCall.id.desc())
            )
        )
        pending = next((call for call in calls if call.status == "PENDING_APPROVAL"), None)
        running = next((call for call in calls if call.status == "RUNNING"), None)
        terminal_running = False
        # No ToolCall exists yet: a crash can strand the initially linked
        # AgentRun during its first provider invocation. This is a terminal
        # recovery only; never retry the initial provider call.
        initial_without_tool = not calls and step.status == "RUNNING" and agent.status == "RUNNING"
        # Proposal and suspension are separate commits. A crash in between
        # leaves a pending approval with a still-running workflow step.
        if pending is not None:
            if step.status != "RUNNING" or agent.status not in {"RUNNING", "WAITING_FOR_APPROVAL"}:
                continue
            candidate = pending
            claimed_at = pending.created_at
            stamp = None
        else:
            candidate = None
        if candidate is None and running is not None:
            # The very first tool can commit RUNNING before a continuation
            # claim exists. A crashed executor must never be replayed.
            if step.status != "RUNNING" or agent.status != "RUNNING":
                continue
            candidate = running
            claimed_at = running.started_at
            stamp = None
        claimed = next(
            (
                call
                for call in calls
                if (call.result_metadata or {}).get("continuation_claimed") is True
            ),
            None,
        )
        if candidate is None:
            if agent.status == "WAITING_FOR_APPROVAL":
                # Approval-linked execution can commit before its continuation
                # claim, or a denial can commit before failing the waiting step.
                # In either case no pending ToolCall remains to resume.
                terminal_tool = next(
                    (
                        call
                        for call in calls
                        if call.tool_id == "workspace.replace_text"
                        and call.approval_request_id is not None
                        and call.status in {"SUCCEEDED", "BLOCKED", "FAILED"}
                        and (call.result_metadata or {}).get("continuation_claimed") is not True
                    ),
                    None,
                )
                if step.status != "WAITING_FOR_APPROVAL" or terminal_tool is None:
                    continue
                candidate = terminal_tool
                claimed_at = terminal_tool.completed_at
                stamp = None
            else:
                if claimed is None:
                    # A first tool may finish before the following provider
                    # continuation or AgentRun/step completion is persisted.
                    terminal = next(
                        (
                            call
                            for call in calls
                            if call.status in {"SUCCEEDED", "BLOCKED", "FAILED"}
                        ),
                        None,
                    )
                    if step.status != "RUNNING" or (terminal is None and not initial_without_tool):
                        continue
                    if terminal is not None:
                        candidate = terminal
                        claimed_at = terminal.completed_at
                        stamp = None
                        terminal_running = True
                else:
                    candidate = claimed
                    stamp = (claimed.result_metadata or {}).get("continuation_claimed_at")
                    if not isinstance(stamp, str):
                        continue
                    try:
                        claimed_at = datetime.fromisoformat(stamp)
                    except ValueError:
                        continue
        if candidate is None and initial_without_tool:
            claimed_at = agent.started_at
            stamp = None
        elif candidate is None:
            continue
        if claimed_at is None:
            continue
        if claimed_at.tzinfo is None or instant - claimed_at < _CONTINUATION_LEASE:
            continue
        # Serialize with fresh proposal reservations on AgentRun before
        # reading ToolCalls; otherwise a pending proposal can appear after the
        # last check and before the terminal transition.
        fresh_agent = await session.scalar(
            select(AgentRun)
            .where(
                AgentRun.id == agent.id,
                AgentRun.tenant_id == tenant_id,
                AgentRun.workspace_id == workspace_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if fresh_agent is None:
            await session.rollback()
            return False
        # Lock the same ToolCall used by approval resume and recheck under lock.
        if candidate is not None:
            await session.refresh(candidate, with_for_update=True)
        if pending is not None and (candidate is None or candidate.status != "PENDING_APPROVAL"):
            await session.rollback()
            return False
        if (
            pending is None
            and running is not None
            and (
                candidate is None
                or candidate.status != "RUNNING"
                or candidate.started_at != claimed_at
            )
        ):
            await session.rollback()
            return False
        if (
            pending is None
            and stamp is not None
            and (
                candidate is None
                or (candidate.result_metadata or {}).get("continuation_claimed_at") != stamp
            )
        ):
            await session.rollback()
            return False
        if (
            pending is None
            and running is None
            and stamp is None
            and not initial_without_tool
            and (candidate is None or candidate.status not in {"SUCCEEDED", "BLOCKED", "FAILED"})
        ):
            await session.rollback()
            return False
        if (
            pending is None
            and running is None
            and stamp is None
            and not initial_without_tool
            and (
                candidate is None
                or (candidate.result_metadata or {}).get("continuation_claimed") is True
                or candidate.completed_at != claimed_at
            )
        ):
            await session.rollback()
            return False
        fresh_calls = list(
            await session.scalars(
                select(ToolCall)
                .where(ToolCall.agent_run_id == agent.id)
                .order_by(ToolCall.created_at.desc(), ToolCall.id.desc())
                .execution_options(populate_existing=True)
            )
        )
        latest_pending = next(
            (call for call in fresh_calls if call.status == "PENDING_APPROVAL"), None
        )
        latest_running = next((call for call in fresh_calls if call.status == "RUNNING"), None)
        latest_terminal = next(
            (call for call in fresh_calls if call.status in {"SUCCEEDED", "BLOCKED", "FAILED"}),
            None,
        )
        latest_claim = next(
            (
                call
                for call in fresh_calls
                if (call.result_metadata or {}).get("continuation_claimed") is True
            ),
            None,
        )
        if (
            (
                initial_without_tool
                and (
                    fresh_calls
                    or fresh_agent.started_at != claimed_at
                    or fresh_agent.status != "RUNNING"
                )
            )
            or (pending is None and latest_pending is not None)
            or (running is None and latest_running is not None)
            or (
                pending is not None
                and (latest_pending is None or latest_pending.id != candidate.id)
            )
            or (
                terminal_running and (latest_terminal is None or latest_terminal.id != candidate.id)
            )
            or (
                pending is None
                and running is not None
                and (latest_running is None or latest_running.id != candidate.id)
            )
            or (
                pending is None
                and stamp is not None
                and (latest_claim is None or latest_claim.id != candidate.id)
            )
        ):
            await session.rollback()
            return False
        fresh_step = await session.scalar(
            select(WorkflowStepRun)
            .where(
                WorkflowStepRun.id == step.id,
                WorkflowStepRun.workflow_run_id == workflow_run_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            fresh_step is None
            or fresh_step.status not in {"RUNNING", "WAITING_FOR_APPROVAL"}
            or fresh_agent is None
            or fresh_agent.status not in {"RUNNING", "WAITING_FOR_APPROVAL", "SUCCEEDED", "FAILED"}
            or (pending is not None and fresh_step.status != "RUNNING")
            or (
                initial_without_tool
                and (fresh_step.status != "RUNNING" or fresh_step.agent_run_id != fresh_agent.id)
            )
            or (
                pending is None
                and running is None
                and stamp is None
                and not initial_without_tool
                and (
                    (
                        not terminal_running
                        and (
                            fresh_agent.status != "WAITING_FOR_APPROVAL"
                            or fresh_step.status != "WAITING_FOR_APPROVAL"
                        )
                    )
                    or (terminal_running and fresh_step.status != "RUNNING")
                )
            )
        ):
            await session.rollback()
            return False
        if fresh_agent.status in {"RUNNING", "WAITING_FOR_APPROVAL"}:
            updated = await agent_repository.transition_run(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=fresh_agent.id,
                expected_status=fresh_agent.status,
                values={
                    "status": "FAILED",
                    "failure_code": _INTERRUPTED,
                    "completed_at": instant,
                    "updated_at": instant,
                },
            )
            if updated is None:
                await session.rollback()
                return False
        if pending is not None or running is not None:
            await tool_repository.set_state(
                session,
                tool_call_id=candidate.id,
                status="BLOCKED" if pending is not None else "FAILED",
                failure_code=_INTERRUPTED,
                completed_at=instant,
            )
        running_models = list(
            await session.scalars(
                select(ModelRun).where(
                    ModelRun.agent_run_id == fresh_agent.id,
                    ModelRun.tenant_id == tenant_id,
                    ModelRun.workspace_id == workspace_id,
                    ModelRun.status == "RUNNING",
                )
            )
        )
        for model in running_models:
            updated = await model_repository.transition_running(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                model_run_id=model.id,
                values={
                    "status": "FAILED",
                    "failure_code": _INTERRUPTED,
                    "completed_at": instant,
                    "updated_at": instant,
                },
            )
            if updated is None:
                await session.rollback()
                return False
        updated_step = await workflow_repository.transition_step_run(
            session,
            run_id=workflow_run_id,
            step_run_id=fresh_step.id,
            expected=fresh_step.status,
            values={
                "status": "FAILED",
                "failure_code": _INTERRUPTED,
                "completed_at": instant,
                "updated_at": instant,
            },
        )
        updated_run = await workflow_repository.transition_run(
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
        if updated_step is None or updated_run is None:
            await session.rollback()
            return False
        await session.commit()
        return True
    return False


async def _linked_state(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
):
    tool_call = await tool_repository.get_for_approval(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_request_id=approval_id,
    )
    if tool_call is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    step_run = await workflow_repository.step_run_for_agent(
        session, agent_run_id=tool_call.agent_run_id
    )
    if step_run is None:
        raise ApplicationError(
            "approval_resume_context_invalid", "Approval resume context is invalid", status_code=409
        )
    workflow_run = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == step_run.workflow_run_id,
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
        )
    )
    if workflow_run is None or (workflow_run.project_id, workflow_run.task_id) != (
        tool_call.project_id,
        tool_call.task_id,
    ):
        raise ApplicationError(
            "approval_resume_context_invalid", "Approval resume context is invalid", status_code=409
        )
    return tool_call, step_run, workflow_run


async def _fail_waiting(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_run_id: UUID,
    workflow_run_id: UUID,
    step_run_id: UUID,
    code: str,
) -> None:
    await agent_service.fail_waiting_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=agent_run_id,
        failure_code=code,
    )
    await workflow_service.transition_step(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=workflow_run_id,
        step_run_id=step_run_id,
        expected=WorkflowStepRunStatus.WAITING_FOR_APPROVAL,
        target=WorkflowStepRunStatus.FAILED,
        failure_code=code,
    )
    await workflow_service.fail_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=workflow_run_id,
        failure_code=code,
    )


async def approve_and_resume(
    session: AsyncSession,
    *,
    registry: ProviderRegistry,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
) -> ApprovalRequest:
    tool_call, step_run, workflow_run = await _linked_state(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
    )
    previous = await approval_service.get_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    if previous.status == "PENDING" and step_run.status != "WAITING_FOR_APPROVAL":
        raise ApplicationError(
            "approval_resume_invalid_state", "Approval resume state is invalid", status_code=409
        )
    approval = await approval_service.approve(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    if step_run.status == WorkflowStepRunStatus.COMPLETED.value:
        return approval
    configured_root = get_settings().workspace_root
    if configured_root is None:
        raise ApplicationError(
            "workspace_root_unavailable", "Approved workspace root is unavailable", status_code=409
        )
    try:
        workspace_root = WorkspaceRoot.approved(configured_root)
    except ToolExecutionError:
        raise ApplicationError(
            "workspace_root_unavailable", "Approved workspace root is unavailable", status_code=409
        ) from None
    gateway, agent_run = await tool_service.resume_prepared_mutation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
        workspace_root=workspace_root,
    )
    if gateway.status != ToolExecutionStatus.SUCCEEDED or gateway.evidence is None:
        code = gateway.failure_code or "tool_execution_failed"
        if agent_run.status == AgentRunStatus.WAITING_FOR_APPROVAL.value:
            await _fail_waiting(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                agent_run_id=agent_run.id,
                workflow_run_id=workflow_run.id,
                step_run_id=step_run.id,
                code=code,
            )
        return approval
    definition, assignment = await specializations.developer_assignment_for_resume(
        session, run=workflow_run, step_run=step_run
    )
    if tool_call.proposal_model_run_id is None:
        await _fail_waiting(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_run_id=agent_run.id,
            workflow_run_id=workflow_run.id,
            step_run_id=step_run.id,
            code="approval_resume_context_invalid",
        )
        return approval
    initial_model_run = await session.scalar(
        select(ModelRun).where(
            ModelRun.id == tool_call.proposal_model_run_id,
            ModelRun.agent_run_id == agent_run.id,
            ModelRun.tenant_id == tenant_id,
            ModelRun.workspace_id == workspace_id,
            ModelRun.status == "SUCCEEDED",
        )
    )
    if initial_model_run is None or definition.id != agent_run.agent_definition_id:
        await _fail_waiting(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_run_id=agent_run.id,
            workflow_run_id=workflow_run.id,
            step_run_id=step_run.id,
            code="approval_resume_context_invalid",
        )
        return approval
    # A repair cycle can wait for multiple distinct approvals. Claim the
    # continuation on THIS exact mutation, atomically with the AgentRun CAS;
    # replaying an earlier approval must never consume a later approval wait.
    await session.refresh(agent_run, with_for_update=True)
    await session.refresh(tool_call, with_for_update=True)
    if (tool_call.result_metadata or {}).get("continuation_claimed") is True:
        await reconcile_stale_continuation(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_run_id=workflow_run.id,
        )
        return approval
    instant = datetime.now(UTC)
    tool_call.result_metadata = {
        **(tool_call.result_metadata or {}),
        "continuation_claimed": True,
        "continuation_claimed_at": instant.isoformat(),
    }
    agent_run = await agent_repository.transition_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=agent_run.id,
        expected_status=AgentRunStatus.WAITING_FOR_APPROVAL.value,
        values={"status": AgentRunStatus.RUNNING.value, "updated_at": instant},
    )
    if agent_run is None:
        await session.rollback()
        # Another identical approval request already claimed the single continuation.
        return approval
    step_run = await workflow_repository.transition_step_run(
        session,
        run_id=workflow_run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.WAITING_FOR_APPROVAL.value,
        values={"status": WorkflowStepRunStatus.RUNNING.value, "updated_at": instant},
    )
    if step_run is None:
        await session.rollback()
        raise ApplicationError(
            "workflow_step_invalid_transition",
            "Workflow step state transition is invalid",
            status_code=409,
        )
    await session.commit()
    response = await developer_service.continue_assignment(
        session,
        registry=registry,
        run=agent_run,
        definition=definition,
        data=assignment,
        initial_model_run=initial_model_run,
        evidence=gateway.evidence,
    )
    if response.status == AgentRunStatus.WAITING_FOR_APPROVAL:
        await workflow_service.transition_step(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=workflow_run.id,
            step_run_id=step_run.id,
            expected=WorkflowStepRunStatus.RUNNING,
            target=WorkflowStepRunStatus.WAITING_FOR_APPROVAL,
        )
        return approval
    if response.status != AgentRunStatus.SUCCEEDED or response.result is None:
        failure_code = response.error_code or "agent_execution_failed"
        await workflow_service.transition_step(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=workflow_run.id,
            step_run_id=step_run.id,
            expected=WorkflowStepRunStatus.RUNNING,
            target=WorkflowStepRunStatus.FAILED,
            failure_code=failure_code,
        )
        await workflow_service.fail_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=workflow_run.id,
            failure_code=failure_code,
        )
        return approval
    await specializations.persist_next_handoff(
        session, run=workflow_run, step_run=step_run, result=response.result
    )
    await workflow_service.transition_step(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=workflow_run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.RUNNING,
        target=WorkflowStepRunStatus.COMPLETED,
    )
    return approval


async def reject_and_terminalize(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
) -> ApprovalRequest:
    approval = await approval_service.reject(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    _, step_run, workflow_run = await _linked_state(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
    )
    if step_run.status == WorkflowStepRunStatus.FAILED.value:
        return approval
    agent_run = await tool_service.reject_prepared_mutation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
    )
    if agent_run.status == AgentRunStatus.WAITING_FOR_APPROVAL.value:
        await _fail_waiting(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            agent_run_id=agent_run.id,
            workflow_run_id=workflow_run.id,
            step_run_id=step_run.id,
            code="approval_rejected",
        )
    return approval
