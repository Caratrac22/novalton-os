"""Permission- and Policy-gated execution of server-owned read-only tools."""

import asyncio
import hashlib
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.approvals import service as approvals_service
from novalton_api.modules.approvals.schemas import ApprovalCreate
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationContext,
    PolicyEvaluationRequest,
)
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.runtime_events.service import append_event
from novalton_api.modules.tools import repository
from novalton_api.modules.tools.contracts import (
    ToolEvidence,
    ToolExecutionStatus,
    ToolGatewayResult,
    ToolProposal,
    WorkspaceSearchTextInput,
)
from novalton_api.modules.tools.executor import (
    TRUSTED_TOOL_REGISTRY,
    ToolExecutionError,
    ToolRegistry,
    WorkspaceRoot,
)
from novalton_api.modules.tools.models import ToolCall
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStepRun


def _result(
    value: ToolCall, *, evidence: ToolEvidence | None = None, failure_code: str | None = None
) -> ToolGatewayResult:
    return ToolGatewayResult(
        tool_call_id=str(value.id),
        status=ToolExecutionStatus(value.status),
        policy_effect=value.policy_effect,
        approval_id=str(value.approval_request_id) if value.approval_request_id else None,
        evidence=evidence,
        failure_code=failure_code or value.failure_code,
    )


def _safe_input_metadata(value: Any) -> dict[str, object]:
    data = value.model_dump(mode="json")
    if isinstance(value, WorkspaceSearchTextInput):
        query = value.query
        data.pop("query", None)
        data["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
        data["query_length"] = len(query)
    return data


def _policy_resource(run: AgentRun) -> tuple[str | None, UUID | None]:
    if run.task_id is not None:
        return "task", run.task_id
    if run.project_id is not None:
        return "project", run.project_id
    return None, None


def _policy_request(*, run: AgentRun, action: str, tool_call_id: UUID) -> PolicyEvaluationRequest:
    resource_type, resource_id = _policy_resource(run)
    return PolicyEvaluationRequest(
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        action=action,
        actor_type="agent",
        actor_id=f"toolcall:{tool_call_id}",
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=run.project_id,
        task_id=run.task_id,
        context=PolicyEvaluationContext(
            risk_level="LOW", environment=get_settings().environment, reversible=True
        ),
    )


async def _load_authority(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_run_id: UUID,
    proposal_model_run_id: UUID | None,
) -> tuple[AgentRun, AgentDefinition]:
    run = await session.scalar(
        select(AgentRun).where(
            AgentRun.id == agent_run_id,
            AgentRun.tenant_id == tenant_id,
            AgentRun.workspace_id == workspace_id,
        )
    )
    if run is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    if run.status != "RUNNING":
        raise ApplicationError(
            "tool_agent_run_inactive", "Agent run is not active", status_code=409
        )
    definition = await session.scalar(
        select(AgentDefinition).where(
            AgentDefinition.id == run.agent_definition_id,
            AgentDefinition.tenant_id == tenant_id,
            AgentDefinition.workspace_id == workspace_id,
        )
    )
    if definition is None or definition.version != run.agent_version:
        raise ApplicationError(
            "tool_agent_authority_invalid", "Agent authority is invalid", status_code=409
        )
    if proposal_model_run_id is not None:
        model_run = await session.scalar(
            select(ModelRun).where(
                ModelRun.id == proposal_model_run_id,
                ModelRun.tenant_id == tenant_id,
                ModelRun.workspace_id == workspace_id,
                ModelRun.agent_run_id == run.id,
            )
        )
        if model_run is None:
            raise ApplicationError(
                "tool_model_linkage_invalid", "Tool proposal linkage is invalid", status_code=409
            )
    return run, definition


async def _observable(
    session: AsyncSession, *, value: ToolCall, event_type: str, outcome: str
) -> None:
    payload: dict[str, object] = {
        "tool_call_id": str(value.id),
        "agent_run_id": str(value.agent_run_id),
        "tool_name": value.tool_id,
        "status": value.status,
        "execution_target_class": value.execution_target_class,
    }
    workflow_link = (
        await session.execute(
            select(WorkflowRun.id, WorkflowStepRun.id)
            .join(WorkflowStepRun, WorkflowStepRun.workflow_run_id == WorkflowRun.id)
            .where(WorkflowStepRun.agent_run_id == value.agent_run_id)
        )
    ).first()
    if workflow_link is not None:
        payload["workflow_run_id"] = str(workflow_link[0])
        payload["workflow_step_run_id"] = str(workflow_link[1])
    if value.policy_effect is not None:
        payload["policy_effect"] = value.policy_effect
    if value.failure_code is not None:
        payload["failure_code"] = value.failure_code
    if value.result_metadata is not None:
        for key in ("result_count", "bytes_returned", "truncated", "duration_ms"):
            if key in value.result_metadata:
                payload[key] = value.result_metadata[key]
    await append_event(
        session,
        data=RuntimeEventCreate(
            tenant_id=value.tenant_id,
            workspace_id=value.workspace_id,
            project_id=value.project_id,
            task_id=value.task_id,
            event_type=event_type,
            source="tool_gateway",
            payload=payload,
        ),
        commit=False,
    )
    resource_type, resource_id = (
        ("task", value.task_id)
        if value.task_id is not None
        else ("project", value.project_id)
        if value.project_id is not None
        else (None, None)
    )
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=value.tenant_id,
            workspace_id=value.workspace_id,
            project_id=value.project_id,
            task_id=value.task_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action="tool.execute",
            actor_type="service",
            outcome=outcome,  # type: ignore[arg-type]
            metadata={
                "tool_call_id": str(value.id),
                "agent_run_id": str(value.agent_run_id),
                "tool_name": value.tool_id,
                "status": value.status,
                "policy_effect": value.policy_effect,
                "failure_code": value.failure_code,
            },
        ),
        commit=False,
    )


async def _deny(
    session: AsyncSession,
    *,
    value: ToolCall,
    code: str,
    policy_effect: str | None = None,
    matched_rule_ids: list[str] | None = None,
) -> ToolGatewayResult:
    value = await repository.set_state(
        session,
        tool_call_id=value.id,
        status="BLOCKED",
        policy_effect=policy_effect,
        matched_rule_ids=matched_rule_ids,
        failure_code=code,
        completed_at=datetime.now(UTC),
    )
    await _observable(session, value=value, event_type="tool.call.blocked", outcome="blocked")
    await session.commit()
    return _result(value)


async def execute_proposal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    agent_run_id: UUID,
    proposal: ToolProposal,
    permitted_tools: list[str],
    workspace_root: WorkspaceRoot,
    proposal_model_run_id: UUID | None = None,
    approval_id: UUID | None = None,
    registry: ToolRegistry = TRUSTED_TOOL_REGISTRY,
) -> ToolGatewayResult:
    """Execute at most once after exact permission, Policy, and optional approval checks."""
    run, definition = await _load_authority(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
        proposal_model_run_id=proposal_model_run_id,
    )
    registered = registry.get(proposal.tool_name)
    parsed_input = None
    proposal_arguments = proposal.arguments.model_dump(mode="json", exclude_none=True)
    safe_input: dict[str, object] = {"argument_count": len(proposal_arguments)}
    if registered is not None:
        try:
            parsed_input = registered.executor.input_model.model_validate(
                proposal_arguments, strict=True
            )
        except ValidationError:
            parsed_input = None
        if parsed_input is not None:
            safe_input = _safe_input_metadata(parsed_input)

    existing = await repository.get_by_key(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
        call_key=proposal.call_key,
    )
    if existing is not None:
        if existing.tool_id != proposal.tool_name or existing.safe_input_metadata != safe_input:
            return _result(existing, failure_code="tool_call_replay_mismatch")
        if existing.status != "PENDING_APPROVAL":
            return _result(existing)
        value = existing
    else:
        value = await repository.create(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=run.project_id,
            task_id=run.task_id,
            agent_run_id=run.id,
            proposal_model_run_id=proposal_model_run_id,
            call_key=proposal.call_key,
            tool_id=proposal.tool_name,
            safe_input_metadata=safe_input,
        )
        await session.commit()

    if registered is None:
        return await _deny(session, value=value, code="unknown_tool_denied")
    if parsed_input is None:
        return await _deny(session, value=value, code="invalid_tool_input")
    if (
        proposal.tool_name not in permitted_tools
        or registered.definition.required_permission not in definition.permissions
    ):
        return await _deny(session, value=value, code="tool_permission_denied")

    request = _policy_request(
        run=run, action=registered.definition.policy_action, tool_call_id=value.id
    )
    if value.status == "PENDING_APPROVAL":
        if approval_id is None or value.approval_request_id != approval_id:
            return _result(value, failure_code="approval_not_satisfied")
        decision = await policy_service.evaluate(session, request=request)
        policy_effect = decision.effect
        matched_rule_ids = [str(rule_id) for rule_id in decision.matched_rule_ids]
        if decision.effect == PolicyEffect.BLOCK:
            return await _deny(
                session,
                value=value,
                code="tool_policy_blocked",
                policy_effect=decision.effect.value,
                matched_rule_ids=matched_rule_ids,
            )
        if not await approvals_service.is_approval_satisfied(
            session, approval_id=approval_id, request=request
        ):
            return _result(value, failure_code="approval_not_satisfied")
    else:
        decision = await policy_service.evaluate(session, request=request)
        policy_effect = decision.effect
        matched_rule_ids = [str(rule_id) for rule_id in decision.matched_rule_ids]
        if decision.effect == PolicyEffect.BLOCK:
            return await _deny(
                session,
                value=value,
                code="tool_policy_blocked",
                policy_effect=decision.effect.value,
                matched_rule_ids=matched_rule_ids,
            )
        if decision.effect == PolicyEffect.REQUIRE_CONFIRMATION:
            approval = await approvals_service.create_approval(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                data=ApprovalCreate(
                    action=request.action,
                    requester_actor_type="agent",
                    requester_actor_id=request.actor_id,
                    resource_type=request.resource_type,
                    resource_id=request.resource_id,
                    project_id=request.project_id,
                    task_id=request.task_id,
                    context=request.context,
                ),
            )
            value = await repository.set_state(
                session,
                tool_call_id=value.id,
                status="PENDING_APPROVAL",
                policy_effect=decision.effect.value,
                matched_rule_ids=matched_rule_ids,
                approval_request_id=approval.id,
            )
            await _observable(
                session, value=value, event_type="tool.call.approval_required", outcome="success"
            )
            await session.commit()
            return _result(value)

    started = datetime.now(UTC)
    value = await repository.set_state(
        session,
        tool_call_id=value.id,
        status="RUNNING",
        policy_effect=policy_effect.value,
        matched_rule_ids=matched_rule_ids,
        started_at=started,
    )
    await session.commit()
    timer = perf_counter()
    try:
        evidence_data, result_metadata = await asyncio.to_thread(
            registered.executor.execute, workspace_root, parsed_input
        )
    except ToolExecutionError as error:
        value = await repository.set_state(
            session,
            tool_call_id=value.id,
            status="FAILED",
            failure_code=error.code,
            completed_at=datetime.now(UTC),
            result_metadata={"duration_ms": round((perf_counter() - timer) * 1000, 3)},
        )
        await _observable(session, value=value, event_type="tool.call.failed", outcome="failure")
        await session.commit()
        return _result(value)
    duration_ms = round((perf_counter() - timer) * 1000, 3)
    result_metadata = {**result_metadata, "duration_ms": duration_ms}
    value = await repository.set_state(
        session,
        tool_call_id=value.id,
        status="SUCCEEDED",
        result_metadata=result_metadata,
        completed_at=datetime.now(UTC),
    )
    await _observable(session, value=value, event_type="tool.call.completed", outcome="success")
    await session.commit()
    return _result(
        value,
        evidence=ToolEvidence(
            tool_name=proposal.tool_name,
            call_key=proposal.call_key,
            data=evidence_data,
        ),
    )
