"""Backend-authoritative approval resolution for one prepared workspace mutation."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.agents import service as agent_service
from novalton_api.modules.agents.schemas import AgentRunStatus
from novalton_api.modules.approvals import service as approval_service
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.orchestrator import specializations
from novalton_api.modules.tools import repository as tool_repository
from novalton_api.modules.tools import service as tool_service
from novalton_api.modules.tools.contracts import ToolExecutionStatus
from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot
from novalton_api.modules.workflows import repository as workflow_repository
from novalton_api.modules.workflows import service as workflow_service
from novalton_api.modules.workflows.models import WorkflowRun
from novalton_api.modules.workflows.schemas import WorkflowStepRunStatus


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
    approval = await approval_service.approve(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    tool_call, step_run, workflow_run = await _linked_state(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
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
    try:
        agent_run = await agent_service.resume_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=agent_run.id,
        )
    except ApplicationError as error:
        if error.code != "agent_run_invalid_transition":
            raise
        # Another identical approval request already claimed the single continuation.
        return approval
    step_run = await workflow_service.transition_step(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=workflow_run.id,
        step_run_id=step_run.id,
        expected=WorkflowStepRunStatus.WAITING_FOR_APPROVAL,
        target=WorkflowStepRunStatus.RUNNING,
    )
    response = await developer_service.continue_assignment(
        session,
        registry=registry,
        run=agent_run,
        definition=definition,
        data=assignment,
        initial_model_run=initial_model_run,
        evidence=gateway.evidence,
    )
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
