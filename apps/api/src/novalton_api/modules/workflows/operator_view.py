"""Safe read-only composition for the local workflow operator console."""

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.agents.models import AgentRun
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.orchestrator.models import AgentChallengeResolution
from novalton_api.modules.qa_worker.contracts import QAHumanReviewSummary
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tools import repository as tools_repository
from novalton_api.modules.workflows import repository, service
from novalton_api.modules.workflows.schemas import (
    OperatorAgentRunResponse,
    OperatorChallengeResponse,
    OperatorModelRunResponse,
    OperatorStepDetailResponse,
    OperatorToolCallResponse,
    OperatorWorkflowResponse,
    OperatorWorkflowRunResponse,
    WorkflowPlanResponse,
    WorkflowStepResponse,
)

_ROLES = {
    "manager_plan": "developer_manager",
    "developer_execute": "developer_worker",
    "qa_validate": "qa_worker",
}


async def get_operator_view(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, workflow_run_id: UUID
) -> OperatorWorkflowResponse:
    """Compose only safe status, challenge, and accounting facts within one exact scope."""
    run = await service.get_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=workflow_run_id,
    )
    plan = await service.get_plan(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        plan_id=run.workflow_plan_id,
    )
    steps, dependencies = await service.plan_graph(session, plan)
    step_runs = await repository.step_runs_for_runs(session, run_ids=[run.id])
    step_run_by_step = {item.workflow_step_id: item for item in step_runs}
    step_run_ids = [item.id for item in step_runs]
    agent_run_ids = [item.agent_run_id for item in step_runs if item.agent_run_id is not None]

    challenges = list(
        await session.scalars(
            select(AgentChallengeResolution).where(
                AgentChallengeResolution.tenant_id == tenant_id,
                AgentChallengeResolution.workspace_id == workspace_id,
                AgentChallengeResolution.workflow_run_id == run.id,
                AgentChallengeResolution.workflow_step_run_id.in_(step_run_ids),
            )
        )
    )
    challenge_by_step = {item.workflow_step_run_id: item for item in challenges}

    agent_runs = list(
        await session.scalars(
            select(AgentRun).where(
                AgentRun.tenant_id == tenant_id,
                AgentRun.workspace_id == workspace_id,
                AgentRun.id.in_(agent_run_ids),
            )
        )
    )
    agent_by_id = {item.id: item for item in agent_runs}
    model_runs = list(
        await session.scalars(
            select(ModelRun)
            .where(
                ModelRun.tenant_id == tenant_id,
                ModelRun.workspace_id == workspace_id,
                ModelRun.agent_run_id.in_(agent_run_ids),
            )
            .order_by(ModelRun.created_at.asc(), ModelRun.id.asc())
        )
    )
    model_definition_ids = {
        item.model_definition_id for item in model_runs if item.model_definition_id is not None
    }
    target_classes = dict(
        (
            await session.execute(
                select(ModelDefinition.id, ModelDefinition.execution_target_class).where(
                    ModelDefinition.id.in_(model_definition_ids)
                )
            )
        ).all()
    )
    model_runs_by_agent: dict[UUID, list[OperatorModelRunResponse]] = {}
    for item in model_runs:
        if item.agent_run_id is None:
            continue
        model_runs_by_agent.setdefault(item.agent_run_id, []).append(
            OperatorModelRunResponse(
                id=item.id,
                status=item.status,
                provider_id=item.provider_id,
                provider_model_id=item.provider_model_id,
                execution_target_class=target_classes.get(item.model_definition_id),
                input_tokens=item.input_tokens,
                output_tokens=item.output_tokens,
                total_tokens=item.total_tokens,
                duration_ms=float(item.duration_ms) if item.duration_ms is not None else None,
                failure_code=item.failure_code,
                recovery_attempt_kind=item.recovery_attempt_kind,
                recovery_attempt_index=item.recovery_attempt_index,
            )
        )

    tool_calls_by_agent: dict[UUID, list[OperatorToolCallResponse]] = {}
    for item in await tools_repository.list_for_agent_runs(session, agent_run_ids=agent_run_ids):
        metadata = item.result_metadata or {}
        tool_calls_by_agent.setdefault(item.agent_run_id, []).append(
            OperatorToolCallResponse(
                id=item.id,
                tool_name=item.tool_id,
                status=item.status,
                policy_effect=item.policy_effect,
                approval_request_id=item.approval_request_id,
                execution_target_class="LOCAL",
                duration_ms=(
                    float(metadata["duration_ms"])
                    if isinstance(metadata.get("duration_ms"), int | float)
                    else None
                ),
                result_count=(
                    metadata["result_count"]
                    if isinstance(metadata.get("result_count"), int)
                    else None
                ),
                bytes_returned=(
                    metadata["bytes_returned"]
                    if isinstance(metadata.get("bytes_returned"), int)
                    else None
                ),
                truncated=(
                    metadata["truncated"] if isinstance(metadata.get("truncated"), bool) else None
                ),
                failure_code=item.failure_code,
                target_path=(item.prepared_mutation or {}).get("path")
                if item.prepared_mutation
                else None,
                mutation_fingerprint=item.mutation_fingerprint,
                before_lines=(item.prepared_mutation or {}).get("before_lines")
                if item.prepared_mutation
                else None,
                after_lines=(item.prepared_mutation or {}).get("after_lines")
                if item.prepared_mutation
                else None,
                diff_preview=(item.prepared_mutation or {}).get("diff_preview")
                if item.prepared_mutation
                else None,
                diff_truncated=(item.prepared_mutation or {}).get("diff_truncated")
                if item.prepared_mutation
                else None,
            )
        )

    qa_verdict = next((item.qa_verdict for item in challenges if item.qa_verdict is not None), None)
    if qa_verdict is None:
        event = await session.scalar(
            select(RuntimeEvent)
            .where(
                RuntimeEvent.tenant_id == tenant_id,
                RuntimeEvent.workspace_id == workspace_id,
                RuntimeEvent.project_id == run.project_id,
                RuntimeEvent.task_id == run.task_id,
                RuntimeEvent.payload["workflow_run_id"].astext == str(run.id),
                RuntimeEvent.payload["qa_verdict"].astext.is_not(None),
            )
            .order_by(RuntimeEvent.occurred_at.desc(), RuntimeEvent.id.desc())
            .limit(1)
        )
        if event is not None and event.payload is not None:
            value = event.payload.get("qa_verdict")
            qa_verdict = value if isinstance(value, str) else None
    if qa_verdict is None and run.failure_code in {"qa_failed", "qa_inconclusive"}:
        qa_verdict = "FAIL" if run.failure_code == "qa_failed" else "INCONCLUSIVE"

    key_by_id = {step.id: step.step_key for step in steps}
    depends_on: dict[UUID, list[str]] = {step.id: [] for step in steps}
    for edge in dependencies:
        depends_on[edge.workflow_step_id].append(key_by_id[edge.depends_on_step_id])
    details: list[OperatorStepDetailResponse] = []
    for step in steps:
        step_run = step_run_by_step[step.id]
        challenge = challenge_by_step.get(step_run.id)
        agent = agent_by_id.get(step_run.agent_run_id)
        safe_review_summary = (
            QAHumanReviewSummary.model_validate_json(json.dumps(challenge.safe_review_summary))
            if challenge is not None and challenge.safe_review_summary is not None
            else None
        )
        details.append(
            OperatorStepDetailResponse(
                workflow_step_run_id=step_run.id,
                specialization_role=_ROLES.get(step.step_key),
                challenge=OperatorChallengeResponse(
                    challenge_level=challenge.challenge_level,
                    result_status=challenge.result_status,
                    specialization_role=challenge.specialization_role,
                    qa_verdict=challenge.qa_verdict,
                    review_summary_status=(
                        "AVAILABLE"
                        if challenge.safe_review_summary is not None
                        else "MISSING"
                        if challenge.specialization_role == "qa_worker"
                        else "NOT_APPLICABLE"
                    ),
                    safe_review_summary=safe_review_summary,
                    decision=challenge.decision,
                    decided_at=challenge.decided_at,
                )
                if challenge is not None
                else None,
                agent_run=OperatorAgentRunResponse(
                    id=agent.id,
                    status=agent.status,
                    agent_name=agent.agent_name,
                    agent_slug=agent.agent_slug,
                    failure_code=agent.failure_code,
                    model_runs=model_runs_by_agent.get(agent.id, []),
                    tool_calls=tool_calls_by_agent.get(agent.id, []),
                )
                if agent is not None
                else None,
            )
        )

    return OperatorWorkflowResponse(
        workflow_plan=WorkflowPlanResponse(
            id=plan.id,
            tenant_id=plan.tenant_id,
            workspace_id=plan.workspace_id,
            project_id=plan.project_id,
            task_id=plan.task_id,
            version=plan.version,
            title=plan.title,
            summary=plan.summary,
            change_reason=plan.change_reason,
            steps=[
                WorkflowStepResponse.model_validate(
                    {**step.__dict__, "depends_on": sorted(depends_on[step.id])}
                )
                for step in steps
            ],
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        ),
        workflow_run=OperatorWorkflowRunResponse(
            id=run.id,
            task_id=run.task_id,
            workflow_plan_id=run.workflow_plan_id,
            plan_version=run.plan_version,
            status=run.status,
            failure_code=run.failure_code,
            step_runs=step_runs,
        ),
        step_details=details,
        qa_verdict=qa_verdict,
    )
