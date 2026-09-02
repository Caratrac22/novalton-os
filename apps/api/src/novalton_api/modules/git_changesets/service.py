"""Server-owned preparation and application of exact local Git changesets."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.approvals import service as approvals_service
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.approvals.schemas import ApprovalCreate
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.git_changesets import local, repository
from novalton_api.modules.git_changesets.models import GitCommitAction
from novalton_api.modules.git_changesets.schemas import GitCommitPrepare
from novalton_api.modules.orchestrator.models import AgentChallengeResolution
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationContext,
    PolicyEvaluationRequest,
)
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tools.executor import ToolExecutionError, WorkspaceRoot
from novalton_api.modules.tools.models import ToolCall
from novalton_api.modules.workflows.models import WorkflowRun, WorkflowStep, WorkflowStepRun

_ACTION = "git.commit_changeset"
_IDENTITY = "Novalton OS <novalton@local.invalid>"


def _failure(code: str, message: str = "Git commit action is unavailable") -> ApplicationError:
    return ApplicationError(code, message, status_code=409)


def _root() -> WorkspaceRoot:
    value = get_settings().workspace_root
    if value is None:
        raise _failure("workspace_root_unavailable")
    try:
        return WorkspaceRoot.approved(value)
    except ToolExecutionError:
        raise _failure("workspace_root_unavailable") from None


async def _workflow(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, workflow_run_id: UUID
) -> WorkflowRun:
    value = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.id == workflow_run_id,
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workspace_id == workspace_id,
        )
    )
    if value is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    if value.status != "COMPLETED":
        raise _failure("git_workflow_not_completed")
    return value


async def _qa_eligible(session: AsyncSession, run: WorkflowRun) -> None:
    challenges = list(
        (
            await session.scalars(
                select(AgentChallengeResolution)
                .where(
                    AgentChallengeResolution.tenant_id == run.tenant_id,
                    AgentChallengeResolution.workspace_id == run.workspace_id,
                )
                .join(
                    WorkflowStepRun,
                    WorkflowStepRun.id == AgentChallengeResolution.workflow_step_run_id,
                )
                .where(WorkflowStepRun.workflow_run_id == run.id)
            )
        ).all()
    )
    qa = [item for item in challenges if item.specialization_role == "qa_worker"]
    if len(qa) > 1:
        raise _failure("git_qa_ineligible")
    if qa:
        value = qa[0]
        if value.qa_verdict not in {"PASS", "PASS_WITH_WARNINGS"}:
            raise _failure("git_qa_ineligible")
        if value.challenge_level == "BLOCK_RECOMMENDED" or (
            value.challenge_level == "HUMAN_REVIEW_RECOMMENDED"
            and value.decision != "ACCEPT_RESULT"
        ):
            raise _failure("git_qa_ineligible")
    else:
        # A clean QA PASS creates a runtime event, not a human challenge.  Warnings
        # never take this route: they must have an accepted I-037 challenge.
        event = await session.scalar(
            select(RuntimeEvent)
            .where(
                RuntimeEvent.tenant_id == run.tenant_id,
                RuntimeEvent.workspace_id == run.workspace_id,
                RuntimeEvent.project_id == run.project_id,
                RuntimeEvent.task_id == run.task_id,
                RuntimeEvent.payload["workflow_run_id"].astext == str(run.id),
                RuntimeEvent.payload["specialization_role"].astext == "qa_worker",
                RuntimeEvent.payload["qa_verdict"].astext == "PASS",
            )
            .order_by(RuntimeEvent.occurred_at.desc(), RuntimeEvent.id.desc())
            .limit(1)
        )
        if event is None:
            raise _failure("git_qa_ineligible")
    if any(item.decision is None or item.decision == "REJECT_RESULT" for item in challenges):
        raise _failure("git_challenge_unresolved")


async def _mutations(
    session: AsyncSession, run: WorkflowRun
) -> tuple[list[str], list[dict[str, str]]]:
    developer_steps = list(
        (
            await session.scalars(
                select(WorkflowStepRun)
                .join(WorkflowStep, WorkflowStep.id == WorkflowStepRun.workflow_step_id)
                .where(
                    WorkflowStepRun.workflow_run_id == run.id,
                    WorkflowStep.step_key == "developer_execute",
                )
            )
        ).all()
    )
    if len(developer_steps) != 1 or developer_steps[0].status != "COMPLETED":
        raise _failure("git_developer_ineligible")
    rows = (
        await session.execute(
            select(ToolCall, WorkflowStep)
            .join(WorkflowStepRun, WorkflowStepRun.agent_run_id == ToolCall.agent_run_id)
            .join(WorkflowStep, WorkflowStep.id == WorkflowStepRun.workflow_step_id)
            .join(ApprovalRequest, ApprovalRequest.id == ToolCall.approval_request_id)
            .where(
                ToolCall.tenant_id == run.tenant_id,
                ToolCall.workspace_id == run.workspace_id,
                WorkflowStepRun.workflow_run_id == run.id,
                ToolCall.tool_id == "workspace.replace_text",
                ApprovalRequest.status == "APPROVED",
            )
            .order_by(ToolCall.created_at, ToolCall.id)
        )
    ).all()
    if not rows or any(
        call.status != "SUCCEEDED"
        or step.step_key != "developer_execute"
        or call.mutation_fingerprint is None
        or call.preimage_sha256 is None
        or call.candidate_sha256 is None
        or not isinstance(call.prepared_mutation, dict)
        for call, step in rows
    ):
        raise _failure("git_mutation_evidence_invalid")
    grouped: dict[str, list[ToolCall]] = {}
    for call, _ in rows:
        prepared = call.prepared_mutation or {}
        path = prepared.get("path")
        if not isinstance(path, str):
            raise _failure("git_mutation_evidence_invalid")
        grouped.setdefault(path, []).append(call)
    candidates: list[dict[str, str]] = []
    for path, calls in grouped.items():
        for earlier, later in zip(calls, calls[1:], strict=False):
            if earlier.candidate_sha256 != later.preimage_sha256:
                raise _failure("git_mutation_chain_invalid")
        first, final = calls[0], calls[-1]
        candidates.append(
            {
                "path": path,
                "preimage_sha256": str(first.preimage_sha256),
                "candidate_sha256": str(final.candidate_sha256),
            }
        )
    return [str(call.id) for call, _ in rows], candidates


def _policy(run: WorkflowRun, action_id: UUID) -> PolicyEvaluationRequest:
    return PolicyEvaluationRequest(
        tenant_id=run.tenant_id,
        workspace_id=run.workspace_id,
        action=_ACTION,
        actor_type="service",
        actor_id=f"git-action:{action_id}",
        resource_type="task",
        resource_id=run.task_id,
        project_id=run.project_id,
        task_id=run.task_id,
        context=PolicyEvaluationContext(
            risk_level="HIGH", environment=get_settings().environment, reversible=False
        ),
    )


def _fingerprint(
    preparation: local.LocalPreparation,
    source_ids: list[str],
    data: GitCommitPrepare,
    timestamp: datetime,
    expected: str,
) -> str:
    payload = {
        "version": 1,
        "repository_key": preparation.repository_key,
        "branch": preparation.branch_ref,
        "head": preparation.head_sha,
        "index": preparation.index_fingerprint,
        "sources": source_ids,
        "paths": [item.__dict__ for item in preparation.paths],
        "preview": preparation.preview["diff_sha256"],
        "message": data.commit_message,
        "identity": _IDENTITY,
        "timestamp": timestamp.isoformat(),
        "expected_commit": expected,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _audit(
    session: AsyncSession,
    *,
    action: GitCommitAction,
    outcome: str,
    failure_code: str | None = None,
) -> None:
    """Persist bounded, secret-free operator-action accountability metadata."""
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            project_id=action.project_id,
            task_id=action.task_id,
            resource_type="task",
            resource_id=action.task_id,
            action=_ACTION,
            actor_type="service",
            actor_id=f"git-action:{action.id}",
            outcome=outcome,  # type: ignore[arg-type]
            metadata={
                "git_commit_action_id": str(action.id),
                "workflow_run_id": str(action.workflow_run_id),
                "action_fingerprint": action.action_fingerprint,
                "status": action.status,
                "resulting_commit_sha": action.resulting_commit_sha,
                "failure_code": failure_code,
            },
        ),
        commit=False,
    )


async def prepare(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    data: GitCommitPrepare,
) -> GitCommitAction:
    run = await _workflow(
        session, tenant_id=tenant_id, workspace_id=workspace_id, workflow_run_id=workflow_run_id
    )
    await _qa_eligible(session, run)
    sources, candidates = await _mutations(session, run)
    root = _root()
    timestamp = datetime.now(UTC)
    try:
        preparation = local.prepare(root, candidates)
        expected = local.expected_commit_sha(
            root, preparation, message=data.commit_message, identity=_IDENTITY, timestamp=timestamp
        )
    except ToolExecutionError as error:
        raise _failure(error.code) from None
    fingerprint = _fingerprint(preparation, sources, data, timestamp, expected)
    action = GitCommitAction(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=run.project_id,
        task_id=run.task_id,
        workflow_run_id=run.id,
        repository_key=preparation.repository_key,
        branch_ref=preparation.branch_ref,
        prepared_head_sha=preparation.head_sha,
        index_fingerprint=preparation.index_fingerprint,
        source_tool_call_ids=sources,
        prepared_paths=[
            {
                "path": item.path,
                "preimage_sha256": item.head_sha256,
                "candidate_sha256": item.candidate_sha256,
                "mode": item.mode,
                "head_blob_id": item.head_blob_id,
                "candidate_blob_id": item.candidate_blob_id,
            }
            for item in preparation.paths
        ],
        preview=preparation.preview,
        commit_message=data.commit_message,
        author_identity=_IDENTITY,
        committer_identity=_IDENTITY,
        commit_timestamp=timestamp,
        action_fingerprint=fingerprint,
        policy_effect="REQUIRE_CONFIRMATION",
        expected_commit_sha=expected,
        status="PENDING_APPROVAL",
    )
    session.add(action)
    await session.flush()
    decision = await policy_service.evaluate(session, request=_policy(run, action.id))
    if decision.effect != PolicyEffect.REQUIRE_CONFIRMATION:
        raise _failure("git_confirmation_required")
    approval = await approvals_service.create_approval(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=ApprovalCreate(
            action=_ACTION,
            requester_actor_type="service",
            requester_actor_id=f"git-action:{action.id}",
            resource_type="task",
            resource_id=run.task_id,
            project_id=run.project_id,
            task_id=run.task_id,
            context=PolicyEvaluationContext(
                risk_level="HIGH", environment=get_settings().environment, reversible=False
            ),
            mutation_fingerprint=fingerprint,
        ),
    )
    action.approval_request_id = approval.id
    await _audit(session, action=action, outcome="success")
    await session.commit()
    await session.refresh(action)
    return action


async def approve_and_apply(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, approval_id: UUID
) -> None:
    action = await repository.get_for_approval(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        approval_id=approval_id,
        for_update=True,
    )
    if action is None:
        raise ApplicationError("resource_not_found", "Resource not found", status_code=404)
    if action.status == "APPLIED":
        return
    if action.status not in {"PENDING_APPROVAL", "APPLYING", "FAILED"}:
        raise _failure("git_action_invalid_state")
    run = await _workflow(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        workflow_run_id=action.workflow_run_id,
    )
    await _qa_eligible(session, run)
    source_ids, candidates = await _mutations(session, run)
    if source_ids != action.source_tool_call_ids or [
        {
            "path": item["path"],
            "preimage_sha256": item["preimage_sha256"],
            "candidate_sha256": item["candidate_sha256"],
        }
        for item in sorted(candidates, key=lambda item: item["path"].encode("utf-8"))
    ] != [
        {
            "path": item["path"],
            "preimage_sha256": item["preimage_sha256"],
            "candidate_sha256": item["candidate_sha256"],
        }
        for item in action.prepared_paths
    ]:
        raise _failure("git_stale_changeset")
    request = _policy(run, action.id)
    if (
        (await policy_service.evaluate(session, request=request)).effect
        != PolicyEffect.REQUIRE_CONFIRMATION
        or not await approvals_service.is_approval_satisfied(
            session,
            approval_id=approval_id,
            request=request,
            mutation_fingerprint=action.action_fingerprint,
        )
    ):
        raise _failure("approval_not_satisfied")
    action.status = "APPLYING"
    await session.commit()
    try:
        sha = local.apply(
            _root(),
            action.prepared_paths,
            expected_head=action.prepared_head_sha,
            expected_index=action.index_fingerprint,
            branch_ref=action.branch_ref,
            message=action.commit_message,
            identity=action.committer_identity,
            timestamp=action.commit_timestamp,
            expected_commit=action.expected_commit_sha,
        )
    except ToolExecutionError as error:
        action.status = "FAILED"
        action.failure_code = error.code
        await _audit(session, action=action, outcome="failure", failure_code=error.code)
        await session.commit()
        raise _failure(error.code) from None
    action.status = "APPLIED"
    action.resulting_commit_sha = sha
    action.applied_at = datetime.now(UTC)
    await _audit(session, action=action, outcome="success")
    await session.commit()
