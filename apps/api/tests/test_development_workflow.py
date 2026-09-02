import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.infrastructure.providers.contracts import (
    ContractEnforcementGrade,
    GenerationRequest,
    GenerationResult,
)
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.developer_manager import service as manager_service
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.orchestrator import challenge_repository
from novalton_api.modules.orchestrator.models import AgentChallengeResolution
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.policy.schemas import PolicyEffect, PolicyRuleCreate
from novalton_api.modules.projects.models import Project
from novalton_api.modules.qa_worker import service as qa_service
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.tools.models import ToolCall
from novalton_api.modules.workflows.models import (
    WorkflowPlan,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
    WorkflowStepHandoff,
    WorkflowStepRun,
)
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    model_id: UUID


class QueueProvider:
    provider_id = "mock"

    def __init__(self, results: list[dict[str, object] | str]) -> None:
        self.results = results
        self.calls: list[GenerationRequest] = []

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        result = self.results.pop(0)
        return GenerationResult(
            provider_id=self.provider_id,
            model_id=request.model_id,
            content=result if isinstance(result, str) else json.dumps(result),
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            duration_ms=1,
        )


class SlowQueueProvider(QueueProvider):
    async def complete(self, request: GenerationRequest) -> GenerationResult:
        await asyncio.sleep(0.25)
        return await super().complete(request)


def _base() -> dict[str, object]:
    return {
        "status": "COMPLETED",
        "summary": "Bounded metadata result.",
        "findings": [],
        "artifacts": [],
        "sources": [],
        "assumptions": [],
        "risks": [],
        "uncertainties": [],
        "blocking_issues": [],
        "challenge": {
            "level": "NONE",
            "reason": None,
            "evidence_source_references": [],
            "suggested_action": None,
        },
        "recommended_next_steps": [],
        "requested_actions": [],
    }


def _manager() -> dict[str, object]:
    return _base() | {
        "development_plan": {
            "objective_interpretation": "Deliver the fixed assignment.",
            "architecture_workstreams": ["Service integration"],
            "proposed_tasks": [
                {
                    "task_key": "fixed_assignment",
                    "title": "Implement the fixed assignment",
                    "objective": "Implement metadata-only behavior.",
                    "required_capabilities": ["software_implementation"],
                    "depends_on": [],
                    "expected_output": "development.implementation_result",
                    "acceptance_criteria": ["The behavior is represented."],
                    "risk_level": "LOW",
                }
            ],
            "qa_review": "REQUIRED",
            "security_review": "RECOMMENDED",
            "manual_review": "NOT_NEEDED",
        }
    }


def _worker() -> dict[str, object]:
    return _base() | {
        "task_interpretation": "Implement the fixed assignment.",
        "implementation_summary": "Proposed bounded implementation metadata.",
        "changes": [
            {
                "path": "apps/api/example.py",
                "kind": "MODIFY",
                "rationale": "Represent the behavior.",
                "expected_effect": "The behavior becomes available.",
                "acceptance_criteria": ["criterion_01"],
            }
        ],
        "acceptance_checks": [
            {
                "criterion_id": "criterion_01",
                "status": "SATISFIED",
                "detail": "The proposal covers the criterion.",
            }
        ],
        "test_recommendations": ["Run focused validation later."],
        "blockers": [],
    }


def _qa(verdict: str) -> dict[str, object]:
    status = (
        "PASS"
        if verdict in {"PASS", "PASS_WITH_WARNINGS"}
        else ("FAIL" if verdict == "FAIL" else "NOT_VERIFIED")
    )
    return _base() | {
        "validation_summary": "Validated bounded metadata.",
        "verdict": verdict,
        "acceptance_results": [
            {
                "criterion_id": "criterion_01",
                "status": status,
                "rationale": "The supplied metadata determines this result.",
            }
        ],
        "defects": []
        if verdict != "FAIL"
        else [
            {
                "defect_key": "criterion_failed",
                "title": "Criterion failed",
                "severity": "MEDIUM",
                "description": "The criterion is not satisfied.",
                "affected_criteria": ["criterion_01"],
                "remediation_summary": "Human remediation is required.",
            }
        ],
        "test_recommendations": [],
        "regression_risks": [],
        "security_review_recommendations": [],
        "manual_review_recommendations": [],
        "blockers": ["Evidence is incomplete."] if verdict == "INCONCLUSIVE" else [],
    }


def _challenged(result: dict[str, object]) -> dict[str, object]:
    return result | {
        "challenge": {
            "level": "HUMAN_REVIEW_RECOMMENDED",
            "reason": "A human must confirm the bounded assumption.",
            "evidence_source_references": ["source:fixture"],
            "suggested_action": "Review the assumption.",
        }
    }


async def _seed(
    contract_enforcement_grade: str = ContractEnforcementGrade.PROVIDER_ENFORCED.value,
) -> Scope:
    database = Database.from_settings(Settings.from_environment())
    try:
        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Vertical", slug=f"vertical-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Vertical", slug="vertical")
            session.add(workspace)
            await session.flush()
            project = Project(workspace_id=workspace.id, name="Vertical", slug="vertical")
            session.add(project)
            await session.flush()
            task = Task(project_id=project.id, title="Vertical task")
            definitions = [
                AgentDefinition(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    name=service.DEVELOPER_MANAGER_NAME
                    if service is manager_service
                    else service.DEVELOPER_WORKER_NAME
                    if service is developer_service
                    else service.QA_WORKER_NAME,
                    slug=service.DEVELOPER_MANAGER_SLUG
                    if service is manager_service
                    else service.DEVELOPER_WORKER_SLUG
                    if service is developer_service
                    else service.QA_WORKER_SLUG,
                    version=(
                        developer_service.DEVELOPER_WORKER_VERSION
                        if service is developer_service
                        else 1
                    ),
                    status="ENABLED",
                    category=service.DEVELOPER_MANAGER_CATEGORY
                    if service is manager_service
                    else service.DEVELOPER_WORKER_CATEGORY
                    if service is developer_service
                    else service.QA_WORKER_CATEGORY,
                    mission=service.DEVELOPER_MANAGER_MISSION
                    if service is manager_service
                    else service.DEVELOPER_WORKER_MISSION
                    if service is developer_service
                    else service.QA_WORKER_MISSION,
                    capabilities=service.DEVELOPER_MANAGER_CAPABILITIES
                    if service is manager_service
                    else service.DEVELOPER_WORKER_CAPABILITIES
                    if service is developer_service
                    else service.QA_WORKER_CAPABILITIES,
                    permissions=(
                        developer_service.DEVELOPER_WORKER_PERMISSIONS
                        if service is developer_service
                        else []
                    ),
                )
                for service in (manager_service, developer_service, qa_service)
            ]
            model = ModelDefinition(
                provider_id="mock",
                provider_model_id=f"vertical-{uuid4().hex}",
                display_name="Vertical model",
                status="AVAILABLE",
                context_window=128_000,
                reasoning=True,
                coding=True,
                tool_calling=False,
                structured_output=True,
                contract_enforcement_grade=contract_enforcement_grade,
                enforcement_metadata_source="test_governed_workflow",
                vision=False,
                input_price_per_million=Decimal("1"),
                output_price_per_million=Decimal("1"),
                currency="USD",
                free_allowlisted=False,
            )
            session.add_all([task, *definitions, model])
            await session.flush()
            return Scope(tenant.id, workspace.id, project.id, task.id, model.id)
    finally:
        await database.dispose()


async def _cleanup(scope: Scope) -> None:
    database = Database.from_settings(Settings.from_environment())
    try:
        async with database.session_factory.begin() as session:
            run_ids = select(WorkflowRun.id).where(WorkflowRun.tenant_id == scope.tenant_id)
            plan_ids = select(WorkflowPlan.id).where(WorkflowPlan.tenant_id == scope.tenant_id)
            await session.execute(
                delete(AgentChallengeResolution).where(
                    AgentChallengeResolution.tenant_id == scope.tenant_id
                )
            )
            await session.execute(
                delete(WorkflowStepHandoff).where(WorkflowStepHandoff.workflow_run_id.in_(run_ids))
            )
            await session.execute(
                delete(RuntimeEvent).where(RuntimeEvent.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(AuditRecord).where(AuditRecord.tenant_id == scope.tenant_id)
            )
            await session.execute(delete(ToolCall).where(ToolCall.tenant_id == scope.tenant_id))
            await session.execute(
                delete(ApprovalRequest).where(ApprovalRequest.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id.in_(run_ids))
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(WorkflowStepDependency).where(
                    WorkflowStepDependency.workflow_plan_id.in_(plan_ids)
                )
            )
            await session.execute(
                delete(WorkflowStep).where(WorkflowStep.workflow_plan_id.in_(plan_ids))
            )
            await session.execute(
                delete(WorkflowPlan).where(WorkflowPlan.tenant_id == scope.tenant_id)
            )
            await session.execute(
                update(AgentRun)
                .where(AgentRun.tenant_id == scope.tenant_id)
                .values(model_run_id=None)
            )
            await session.execute(delete(ModelRun).where(ModelRun.tenant_id == scope.tenant_id))
            await session.execute(delete(AgentRun).where(AgentRun.tenant_id == scope.tenant_id))
            await session.execute(
                delete(AgentDefinition).where(AgentDefinition.tenant_id == scope.tenant_id)
            )
            await session.execute(delete(PolicyRule).where(PolicyRule.tenant_id == scope.tenant_id))
            await session.execute(delete(Task).where(Task.id == scope.task_id))
            await session.execute(delete(Project).where(Project.id == scope.project_id))
            await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
            await session.execute(delete(Tenant).where(Tenant.id == scope.tenant_id))
            await session.execute(
                delete(ModelDefinition).where(ModelDefinition.id == scope.model_id)
            )
    finally:
        await database.dispose()


@pytest.fixture
def scope() -> Scope:
    value = asyncio.run(_seed())
    yield value
    asyncio.run(_cleanup(value))


@pytest.mark.parametrize(
    ("verdict", "final_status", "reason"),
    [
        ("PASS", "COMPLETED", None),
        ("PASS_WITH_WARNINGS", "COMPLETED", None),
        ("FAIL", "FAILED", "qa_failed"),
        ("INCONCLUSIVE", "FAILED", "qa_inconclusive"),
    ],
)
def test_fixed_vertical_workflow_is_durable_and_qa_controls_success(
    scope: Scope, verdict: str, final_status: str, reason: str | None
) -> None:
    provider = QueueProvider([_manager(), _worker(), _qa(verdict)])
    base = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks/{scope.task_id}"
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        created = client.post(
            f"{base}/development-workflows",
            json={
                "objective": "Implement one bounded behavior.",
                "acceptance_criteria": ["The behavior is represented."],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert provider.calls == []
        assert [
            (step["step_key"], step["position"], step["depends_on"])
            for step in body["workflow_plan"]["steps"]
        ] == [
            ("manager_plan", 0, []),
            ("developer_execute", 1, ["manager_plan"]),
            ("qa_validate", 2, ["developer_execute"]),
        ]
        advance = (
            f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
            f"/workflow-runs/{body['workflow_run']['id']}/advance"
        )
        first = client.post(advance).json()
        assert first["step_key"] == "manager_plan"
        assert len(provider.calls) == 1
        second = client.post(advance).json()
        assert second["step_key"] == "developer_execute"
        assert len(provider.calls) == 2

    # A fresh app/session proves downstream state is database-backed, not process-local.
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        third = client.post(advance).json()
    assert third["step_key"] == "qa_validate"
    assert third["workflow_status"] == final_status
    assert third["reason_code"] == reason
    assert len(provider.calls) == 3

    async def counts() -> tuple[int, int, int]:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                return (
                    int(
                        await session.scalar(select(func.count()).select_from(WorkflowStepHandoff))
                        or 0
                    ),
                    int(
                        await session.scalar(
                            select(func.count())
                            .select_from(AgentRun)
                            .where(AgentRun.tenant_id == scope.tenant_id)
                        )
                        or 0
                    ),
                    int(
                        await session.scalar(
                            select(func.count())
                            .select_from(ModelRun)
                            .where(ModelRun.tenant_id == scope.tenant_id)
                        )
                        or 0
                    ),
                )
        finally:
            await database.dispose()

    handoffs, agent_runs, model_runs = asyncio.run(counts())
    assert (agent_runs, model_runs) == (3, 3)
    assert handoffs >= 3


def test_benign_approval_required_assignment_proceeds_without_manager_authority(
    scope: Scope,
) -> None:
    provider = QueueProvider([_manager()])
    base = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks/{scope.task_id}"
    )
    objective = (
        "Plan a bounded workspace.replace_text assignment for a harmless test fixture. "
        "The downstream mutation requires deterministic Policy evaluation and explicit human "
        "approval before execution."
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        created = client.post(
            f"{base}/development-workflows",
            json={
                "objective": objective,
                "acceptance_criteria": ["The exact bounded assignment is represented."],
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["workflow_run"]["id"]
        result = client.post(
            f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
            f"/workflow-runs/{run_id}/advance"
        ).json()

    assert result["outcome"] == "STEP_COMPLETED"
    assert result["step_key"] == "manager_plan"
    assert len(provider.calls) == 1
    manager_input = json.loads(provider.calls[0].messages[1].content)["agent_input"]
    assert manager_input["objective"] == objective
    assert manager_input["permitted_tools"] == []
    assert manager_input["constraints"] == [
        "Do not use tools or execute external actions",
        "Remain within the fixed persisted workflow step",
        "Requested actions are proposals only",
    ]


def test_i041_mutation_waits_then_approved_resume_preserves_runs_and_reaches_qa(
    scope: Scope, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def add_confirmation_policy() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                await policy_service.create_rule(
                    session,
                    data=PolicyRuleCreate(
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        name="Confirm exact workspace mutation",
                        action_pattern="tool.workspace.replace_text",
                        effect=PolicyEffect.REQUIRE_CONFIRMATION,
                        actor_type="agent",
                        resource_type="task",
                    ),
                )
        finally:
            await database.dispose()

    asyncio.run(add_confirmation_policy())
    proposal = _worker() | {
        "status": "PARTIAL",
        "tool_proposals": [
            {
                "call_key": "replace_fixture",
                "tool_name": "workspace.replace_text",
                "arguments": {
                    "path": "fixture.txt",
                    "search": "before",
                    "replacement": "after",
                    "expected_matches": 1,
                },
            }
        ],
    }
    provider = QueueProvider([_manager(), proposal, _worker(), _qa("PASS")])
    base = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks/{scope.task_id}"
    )
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            created = client.post(
                f"{base}/development-workflows",
                json={
                    "objective": "Replace the approved fixture marker.",
                    "acceptance_criteria": ["The marker is replaced exactly once."],
                },
            ).json()
            run_id = UUID(str(created["workflow_run"]["id"]))
            advance = (
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
                f"/workflow-runs/{run_id}/advance"
            )
            assert client.post(advance).json()["outcome"] == "STEP_COMPLETED"
            waiting = client.post(advance).json()
            assert waiting["outcome"] == "WAITING_FOR_HUMAN"
            assert waiting["step_status"] == "WAITING_FOR_APPROVAL"
            assert waiting["workflow_status"] == "RUNNING"
            assert target.read_text(encoding="utf-8") == "before\n"

            async def suspended_state():
                database = Database.from_settings(Settings.from_environment())
                try:
                    async with database.session_factory() as session:
                        approval = await session.scalar(
                            select(ApprovalRequest).where(
                                ApprovalRequest.tenant_id == scope.tenant_id
                            )
                        )
                        tool_call = await session.scalar(
                            select(ToolCall).where(ToolCall.tenant_id == scope.tenant_id)
                        )
                        agent_run = await session.get(AgentRun, UUID(str(waiting["agent_run_id"])))
                        return approval, tool_call, agent_run
                finally:
                    await database.dispose()

            approval, tool_call, agent_run = asyncio.run(suspended_state())
            assert approval is not None and tool_call is not None and agent_run is not None
            assert agent_run.status == "WAITING_FOR_APPROVAL"
            assert tool_call.status == "PENDING_APPROVAL"
            assert "candidate_text" not in (tool_call.prepared_mutation or {})
            approval_url = (
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
                f"/approvals/{approval.id}/approve"
            )
            approved = client.post(approval_url)
            assert approved.status_code == 200, approved.text
            assert target.read_text(encoding="utf-8") == "after\n"
            assert len(provider.calls) == 3

            state = asyncio.run(_vertical_state(scope, run_id))
            assert [row[0].status for row in state["rows"]] == [
                "COMPLETED",
                "COMPLETED",
                "READY",
            ]
            assert state["agent_runs"][1].id == UUID(str(waiting["agent_run_id"]))
            assert state["agent_runs"][1].status == "SUCCEEDED"
            assert [item.recovery_attempt_kind for item in state["model_runs"]] == [
                "INITIAL",
                "INITIAL",
                "TOOL_CONTINUATION",
            ]
            replay = client.post(approval_url)
            assert replay.status_code == 200
            assert len(provider.calls) == 3
            qa = client.post(advance).json()
            assert qa["step_key"] == "qa_validate"
            assert qa["workflow_status"] == "COMPLETED"
            assert len(provider.calls) == 4
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("continuation", "expected_code"),
    [
        ("not-json", "invalid_agent_result"),
        (
            _worker()
            | {
                "status": "PARTIAL",
                "tool_proposals": [
                    {
                        "call_key": "another_mutation",
                        "tool_name": "workspace.replace_text",
                        "arguments": {
                            "path": "fixture.txt",
                            "search": "after",
                            "replacement": "again",
                            "expected_matches": 1,
                        },
                    }
                ],
            },
            "tool_round_limit_exceeded",
        ),
    ],
)
def test_i041_delayed_continuation_uses_shared_terminal_validation(
    scope: Scope,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: dict[str, object] | str,
    expected_code: str,
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def add_policy() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                await policy_service.create_rule(
                    session,
                    data=PolicyRuleCreate(
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        name="Confirm classified mutation continuation",
                        action_pattern="tool.workspace.replace_text",
                        effect=PolicyEffect.REQUIRE_CONFIRMATION,
                        actor_type="agent",
                        resource_type="task",
                    ),
                )
        finally:
            await database.dispose()

    asyncio.run(add_policy())
    proposal = _worker() | {
        "status": "PARTIAL",
        "tool_proposals": [
            {
                "call_key": "replace_fixture",
                "tool_name": "workspace.replace_text",
                "arguments": {
                    "path": "fixture.txt",
                    "search": "before",
                    "replacement": "after",
                    "expected_matches": 1,
                },
            }
        ],
    }
    provider = QueueProvider([_manager(), proposal, continuation])
    base = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks/{scope.task_id}"
    )
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            created = client.post(
                f"{base}/development-workflows",
                json={
                    "objective": "Replace the classified fixture marker.",
                    "acceptance_criteria": ["The marker is replaced exactly once."],
                },
            ).json()
            run_id = UUID(str(created["workflow_run"]["id"]))
            advance = (
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
                f"/workflow-runs/{run_id}/advance"
            )
            assert client.post(advance).json()["outcome"] == "STEP_COMPLETED"
            waiting = client.post(advance).json()
            assert waiting["outcome"] == "WAITING_FOR_HUMAN"

            async def approval_and_tool() -> tuple[UUID, UUID]:
                database = Database.from_settings(Settings.from_environment())
                try:
                    async with database.session_factory() as session:
                        approval_id = await session.scalar(
                            select(ApprovalRequest.id).where(
                                ApprovalRequest.tenant_id == scope.tenant_id
                            )
                        )
                        tool_id = await session.scalar(
                            select(ToolCall.id).where(ToolCall.tenant_id == scope.tenant_id)
                        )
                        assert approval_id is not None and tool_id is not None
                        return approval_id, tool_id
                finally:
                    await database.dispose()

            approval_id, tool_id = asyncio.run(approval_and_tool())
            approved = client.post(
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
                f"/approvals/{approval_id}/approve"
            )
            assert approved.status_code == 200
            assert target.read_text(encoding="utf-8") == "after\n"
            assert len(provider.calls) == 3

            state = asyncio.run(_vertical_state(scope, run_id))
            assert state["run"].status == "FAILED"
            assert state["run"].failure_code == expected_code
            assert [row[0].status for row in state["rows"]] == [
                "COMPLETED",
                "FAILED",
                "PENDING",
            ]
            assert state["agent_runs"][1].id == UUID(str(waiting["agent_run_id"]))
            assert state["agent_runs"][1].failure_code == expected_code
            assert [item.recovery_attempt_kind for item in state["model_runs"]] == [
                "INITIAL",
                "INITIAL",
                "TOOL_CONTINUATION",
            ]

            async def final_tool() -> tuple[int, str]:
                database = Database.from_settings(Settings.from_environment())
                try:
                    async with database.session_factory() as session:
                        count = int(
                            await session.scalar(
                                select(func.count())
                                .select_from(ToolCall)
                                .where(ToolCall.tenant_id == scope.tenant_id)
                            )
                            or 0
                        )
                        status = await session.scalar(
                            select(ToolCall.status).where(ToolCall.id == tool_id)
                        )
                        assert status is not None
                        return count, status
                finally:
                    await database.dispose()

            assert asyncio.run(final_tool()) == (1, "SUCCEEDED")
    finally:
        get_settings.cache_clear()


def test_i041_rejection_terminalizes_without_write_or_continuation(
    scope: Scope, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fixture.txt"
    target.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def add_policy() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                await policy_service.create_rule(
                    session,
                    data=PolicyRuleCreate(
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        name="Confirm rejected mutation",
                        action_pattern="tool.workspace.replace_text",
                        effect=PolicyEffect.REQUIRE_CONFIRMATION,
                        actor_type="agent",
                        resource_type="task",
                    ),
                )
        finally:
            await database.dispose()

    asyncio.run(add_policy())
    proposal = _worker() | {
        "status": "PARTIAL",
        "tool_proposals": [
            {
                "call_key": "replace_fixture",
                "tool_name": "workspace.replace_text",
                "arguments": {
                    "path": "fixture.txt",
                    "search": "before",
                    "replacement": "after",
                },
            }
        ],
    }
    provider = QueueProvider([_manager(), proposal])
    base = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks/{scope.task_id}"
    )
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            created = client.post(
                f"{base}/development-workflows",
                json={
                    "objective": "Replace the fixture marker.",
                    "acceptance_criteria": ["The marker is replaced."],
                },
            ).json()
            run_id = UUID(str(created["workflow_run"]["id"]))
            advance = (
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
                f"/workflow-runs/{run_id}/advance"
            )
            client.post(advance)
            waiting = client.post(advance).json()

            async def approval_id() -> UUID:
                database = Database.from_settings(Settings.from_environment())
                try:
                    async with database.session_factory() as session:
                        value = await session.scalar(
                            select(ApprovalRequest.id).where(
                                ApprovalRequest.tenant_id == scope.tenant_id
                            )
                        )
                        assert value is not None
                        return value
                finally:
                    await database.dispose()

            approval = asyncio.run(approval_id())
            rejected = client.post(
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
                f"/approvals/{approval}/reject"
            )
            assert rejected.status_code == 200
            assert target.read_text(encoding="utf-8") == "before\n"
            assert len(provider.calls) == 2
            state = asyncio.run(_vertical_state(scope, run_id))
            assert state["run"].status == "FAILED"
            assert [row[0].status for row in state["rows"]] == [
                "COMPLETED",
                "FAILED",
                "PENDING",
            ]
            assert state["agent_runs"][1].id == UUID(str(waiting["agent_run_id"]))
            assert state["agent_runs"][1].status == "FAILED"
            assert all(
                item.recovery_attempt_kind != "TOOL_CONTINUATION" for item in state["model_runs"]
            )
    finally:
        get_settings.cache_clear()


def test_governed_steps_require_provider_enforced_contracts_before_generation() -> None:
    scope = asyncio.run(_seed(ContractEnforcementGrade.BEST_EFFORT.value))
    provider = QueueProvider([_manager()])
    try:
        created, advance = _create_vertical(scope, provider)
        result = _advance_fresh(provider, advance)
        state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))

        assert (result["outcome"], result["reason_code"]) == (
            "WORKFLOW_FAILED",
            "contract_enforcement_unsatisfied",
        )
        assert [row[0].status for row in state["rows"]] == ["FAILED", "PENDING", "PENDING"]
        assert len(state["agent_runs"]) == 1
        assert state["model_runs"] == []
        assert provider.calls == []
    finally:
        asyncio.run(_cleanup(scope))


async def _vertical_state(scope: Scope, run_id: UUID) -> dict[str, object]:
    """Read the complete persisted vertical state through a new engine/session."""
    database = Database.from_settings(Settings.from_environment())
    try:
        async with database.session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            assert run is not None
            plan = await session.get(WorkflowPlan, run.workflow_plan_id)
            assert plan is not None
            rows = list(
                (
                    await session.execute(
                        select(WorkflowStepRun, WorkflowStep)
                        .join(WorkflowStep, WorkflowStep.id == WorkflowStepRun.workflow_step_id)
                        .where(WorkflowStepRun.workflow_run_id == run_id)
                        .order_by(WorkflowStep.position)
                    )
                ).tuples()
            )
            handoffs = list(
                await session.scalars(
                    select(WorkflowStepHandoff)
                    .where(WorkflowStepHandoff.workflow_run_id == run_id)
                    .order_by(WorkflowStepHandoff.created_at, WorkflowStepHandoff.id)
                )
            )
            agent_runs = list(
                await session.scalars(
                    select(AgentRun)
                    .where(AgentRun.tenant_id == scope.tenant_id)
                    .order_by(AgentRun.created_at, AgentRun.id)
                )
            )
            model_runs = list(
                await session.scalars(
                    select(ModelRun)
                    .where(ModelRun.tenant_id == scope.tenant_id)
                    .order_by(ModelRun.created_at, ModelRun.id)
                )
            )
            events = list(
                await session.scalars(
                    select(RuntimeEvent)
                    .where(RuntimeEvent.tenant_id == scope.tenant_id)
                    .order_by(RuntimeEvent.occurred_at, RuntimeEvent.id)
                )
            )
            resolutions = list(
                await session.scalars(
                    select(AgentChallengeResolution)
                    .where(AgentChallengeResolution.tenant_id == scope.tenant_id)
                    .order_by(AgentChallengeResolution.created_at, AgentChallengeResolution.id)
                )
            )
            plan_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(WorkflowPlan)
                    .where(WorkflowPlan.tenant_id == scope.tenant_id)
                )
                or 0
            )
            workflow_run_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(WorkflowRun)
                    .where(WorkflowRun.tenant_id == scope.tenant_id)
                )
                or 0
            )
            audit_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(AuditRecord)
                    .where(AuditRecord.tenant_id == scope.tenant_id)
                )
                or 0
            )
            audits = list(
                await session.scalars(
                    select(AuditRecord)
                    .where(AuditRecord.tenant_id == scope.tenant_id)
                    .order_by(AuditRecord.occurred_at, AuditRecord.id)
                )
            )
            approval_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ApprovalRequest)
                    .where(ApprovalRequest.tenant_id == scope.tenant_id)
                )
                or 0
            )
            return {
                "run": run,
                "plan": plan,
                "rows": rows,
                "handoffs": handoffs,
                "agent_runs": agent_runs,
                "model_runs": model_runs,
                "events": events,
                "resolutions": resolutions,
                "plan_count": plan_count,
                "workflow_run_count": workflow_run_count,
                "audit_count": audit_count,
                "audits": audits,
                "approval_count": approval_count,
            }
    finally:
        await database.dispose()


def _create_vertical(scope: Scope, provider: QueueProvider) -> tuple[dict[str, object], str]:
    base = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks/{scope.task_id}"
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.post(
            f"{base}/development-workflows",
            json={
                "objective": "I029_SECRET_OBJECTIVE must remain outside runtime events.",
                "acceptance_criteria": ["The full persisted vertical succeeds."],
            },
            headers={"X-Correlation-ID": "i029-correlation"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    advance = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{body['workflow_run']['id']}/advance"
    )
    return body, advance


def _advance_fresh(provider: QueueProvider, url: str) -> dict[str, object]:
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.post(url)
    assert response.status_code == 200, response.text
    return response.json()


def test_i029_full_vertical_integration_across_fresh_app_and_db_boundaries(
    scope: Scope,
) -> None:
    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    created, advance = _create_vertical(scope, provider)
    run_id = UUID(str(created["workflow_run"]["id"]))

    assert [
        (item["step_key"], item["position"], item["depends_on"])
        for item in created["workflow_plan"]["steps"]
    ] == [
        ("manager_plan", 0, []),
        ("developer_execute", 1, ["manager_plan"]),
        ("qa_validate", 2, ["developer_execute"]),
    ]
    initial = asyncio.run(_vertical_state(scope, run_id))
    assert initial["run"].status == "CREATED"  # type: ignore[union-attr]
    assert [row[0].status for row in initial["rows"]] == ["READY", "PENDING", "PENDING"]
    assert [item.handoff_type for item in initial["handoffs"]] == ["DEVELOPMENT_REQUEST"]
    assert initial["agent_runs"] == initial["model_runs"] == initial["events"] == []

    expected = [
        (
            "manager_plan",
            ["COMPLETED", "READY", "PENDING"],
            ["DEVELOPMENT_REQUEST", "MANAGER_ASSIGNMENT"],
        ),
        (
            "developer_execute",
            ["COMPLETED", "COMPLETED", "READY"],
            ["DEVELOPMENT_REQUEST", "MANAGER_ASSIGNMENT", "WORKER_EVIDENCE"],
        ),
        (
            "qa_validate",
            ["COMPLETED", "COMPLETED", "COMPLETED"],
            ["DEVELOPMENT_REQUEST", "MANAGER_ASSIGNMENT", "WORKER_EVIDENCE"],
        ),
    ]
    snapshots: list[dict[str, object]] = []
    for index, (step_key, statuses, handoff_types) in enumerate(expected, start=1):
        result = _advance_fresh(provider, advance)
        assert result["step_key"] == step_key
        state = asyncio.run(_vertical_state(scope, run_id))
        snapshots.append(state)
        assert [row[0].status for row in state["rows"]] == statuses
        assert [item.handoff_type for item in state["handoffs"]] == handoff_types
        assert len(state["agent_runs"]) == len(state["model_runs"]) == index

    final = snapshots[-1]
    assert final["run"].status == "COMPLETED"  # type: ignore[union-attr]
    agent_runs = final["agent_runs"]
    model_runs = final["model_runs"]
    rows = final["rows"]
    assert [item.agent_slug for item in agent_runs] == [
        manager_service.DEVELOPER_MANAGER_SLUG,
        developer_service.DEVELOPER_WORKER_SLUG,
        qa_service.QA_WORKER_SLUG,
    ]
    assert [item.agent_version for item in agent_runs] == [
        1,
        developer_service.DEVELOPER_WORKER_VERSION,
        1,
    ]
    assert [row[1].agent_definition_id for row in rows] == [
        item.agent_definition_id for item in agent_runs
    ]
    assert all(
        item.status == "SUCCEEDED" and item.parent_agent_run_id is None for item in agent_runs
    )
    assert all(
        item.tenant_id == scope.tenant_id and item.workspace_id == scope.workspace_id
        for item in agent_runs
    )
    assert all(
        item.project_id == scope.project_id and item.task_id == scope.task_id for item in agent_runs
    )
    assert {item.model_run_id for item in agent_runs} == {item.id for item in model_runs}
    assert all(item.status == "SUCCEEDED" and item.total_tokens == 15 for item in model_runs)
    assert [row[0].agent_run_id for row in rows] == [item.id for item in agent_runs]
    assert len(provider.calls) == 3
    assert final["plan_count"] == final["workflow_run_count"] == final["audit_count"] == 1
    assert final["approval_count"] == 0

    events = final["events"]
    event_types = [item.event_type for item in events]
    assert event_types == [
        "workflow.run.started",
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.run.completed",
    ]
    assert all(
        item.workspace_id == scope.workspace_id
        and item.project_id == scope.project_id
        and item.task_id == scope.task_id
        and item.correlation_id == "i029-correlation"
        for item in events
    )
    completed = [item.payload for item in events if item.event_type == "workflow.step.completed"]
    assert [item["specialization_role"] for item in completed] == [
        "developer_manager",
        "developer_worker",
        "qa_worker",
    ]
    assert completed[-1]["qa_verdict"] == "PASS"
    serialized_events = json.dumps([item.payload for item in events], sort_keys=True)
    for forbidden in (
        "I029_SECRET_OBJECTIVE",
        "provider",
        "content",
        "credentials",
        "requested_actions",
        "apps/api/example.py",
    ):
        assert forbidden not in serialized_events


def test_i039_operator_view_is_scoped_bounded_and_reports_safe_execution_metadata(
    scope: Scope,
) -> None:
    provider = QueueProvider([_manager(), _worker(), _qa("PASS_WITH_WARNINGS")])
    created, advance = _create_vertical(scope, provider)
    for _ in range(3):
        _advance_fresh(provider, advance)
    run_id = str(created["workflow_run"]["id"])
    url = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{run_id}/operator-view"
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.get(url)
        cross_scope = client.get(url.replace(str(scope.tenant_id), str(uuid4())))

    assert response.status_code == 200, response.text
    assert cross_scope.status_code == 404
    body = response.json()
    assert body["workflow_run"]["status"] == "COMPLETED"
    assert body["qa_verdict"] == "PASS_WITH_WARNINGS"
    assert [item["step_key"] for item in body["workflow_plan"]["steps"]] == [
        "manager_plan",
        "developer_execute",
        "qa_validate",
    ]
    assert [item["specialization_role"] for item in body["step_details"]] == [
        "developer_manager",
        "developer_worker",
        "qa_worker",
    ]
    model_runs = [item["agent_run"]["model_runs"] for item in body["step_details"]]
    assert all(len(items) == 1 for items in model_runs)
    assert all(items[0]["status"] == "SUCCEEDED" for items in model_runs)
    assert all(items[0]["total_tokens"] == 15 for items in model_runs)
    assert all(items[0]["recovery_attempt_kind"] == "INITIAL" for items in model_runs)
    serialized = json.dumps(body, sort_keys=True)
    for forbidden in (
        "I029_SECRET_OBJECTIVE",
        "Bounded metadata result",
        "apps/api/example.py",
        "requested_actions",
        "provider_request_id",
        "correlation_id",
        "handoff",
        "memory",
        "prompt",
    ):
        assert forbidden.casefold() not in serialized.casefold()


@pytest.mark.parametrize(
    ("verdict", "reason"), [("FAIL", "qa_failed"), ("INCONCLUSIVE", "qa_inconclusive")]
)
def test_i029_qa_negative_verdict_never_succeeds(scope: Scope, verdict: str, reason: str) -> None:
    provider = QueueProvider([_manager(), _worker(), _qa(verdict)])
    created, advance = _create_vertical(scope, provider)
    for _ in range(2):
        _advance_fresh(provider, advance)
    result = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))
    assert result["outcome"] == "WORKFLOW_FAILED"
    assert result["reason_code"] == reason
    assert state["run"].status == "FAILED"  # type: ignore[union-attr]
    assert [row[0].status for row in state["rows"]] == ["COMPLETED", "COMPLETED", "FAILED"]
    assert len(state["agent_runs"]) == len(state["model_runs"]) == len(provider.calls) == 3


@pytest.mark.parametrize(
    ("results", "advance_count", "expected_runs"),
    [
        ([_challenged(_manager())], 1, 1),
        ([_manager(), _challenged(_worker())], 2, 2),
    ],
)
def test_i029_meaningful_challenge_stops_downstream_execution(
    scope: Scope, results: list[dict[str, object]], advance_count: int, expected_runs: int
) -> None:
    provider = QueueProvider(results)
    created, advance = _create_vertical(scope, provider)
    result: dict[str, object] = {}
    for _ in range(advance_count):
        result = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))
    assert result["outcome"] == "WAITING_FOR_HUMAN"
    assert result["reason_code"] == "agent_challenge"
    assert len(state["agent_runs"]) == len(state["model_runs"]) == expected_runs
    assert len(provider.calls) == expected_runs
    assert len(state["resolutions"]) == 1
    assert state["resolutions"][0].decision is None
    repeated = _advance_fresh(provider, advance)
    assert repeated["reason_code"] == "agent_challenge"
    assert repeated["challenge_level"] == "HUMAN_REVIEW_RECOMMENDED"
    assert len(provider.calls) == expected_runs


def test_i039_operator_view_exposes_pending_challenge_without_human_reason_or_authority(
    scope: Scope,
) -> None:
    provider = QueueProvider([_challenged(_manager())])
    created, advance = _create_vertical(scope, provider)
    result = _advance_fresh(provider, advance)
    run_id = str(created["workflow_run"]["id"])
    url = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{run_id}/operator-view"
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.get(url)
    assert response.status_code == 200, response.text
    body = response.json()
    active = next(item for item in body["step_details"] if item["challenge"] is not None)
    assert active["workflow_step_run_id"] == result["workflow_step_run_id"]
    assert active["challenge"] == {
        "challenge_level": "HUMAN_REVIEW_RECOMMENDED",
        "result_status": "COMPLETED",
        "specialization_role": "developer_manager",
        "qa_verdict": None,
        "review_summary_status": "NOT_APPLICABLE",
        "safe_review_summary": None,
        "decision": None,
        "decided_at": None,
    }
    assert body["workflow_run"]["status"] == "RUNNING"
    assert (
        next(
            item
            for item in body["workflow_run"]["step_runs"]
            if item["id"] == active["workflow_step_run_id"]
        )["status"]
        == "RUNNING"
    )


def _resolution_url(scope: Scope, run_id: str, step_run_id: str) -> str:
    return (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{run_id}/steps/{step_run_id}/challenge-resolution"
    )


def test_historical_qa_challenge_without_safe_summary_is_explicitly_missing(
    scope: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_pending = challenge_repository.create_pending

    async def create_pre_summary_challenge(session, **values):
        values["safe_review_summary"] = None
        return await create_pending(session, **values)

    monkeypatch.setattr(challenge_repository, "create_pending", create_pre_summary_challenge)
    provider = QueueProvider([_manager(), _worker(), _challenged(_qa("PASS_WITH_WARNINGS"))])
    created, advance = _create_vertical(scope, provider)
    for _ in range(3):
        _advance_fresh(provider, advance)
    run_id = UUID(str(created["workflow_run"]["id"]))

    url = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{run_id}/operator-view"
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.get(url)

    assert response.status_code == 200
    active = next(item for item in response.json()["step_details"] if item["challenge"] is not None)
    assert active["challenge"]["review_summary_status"] == "MISSING"
    assert active["challenge"]["safe_review_summary"] is None
    assert response.json()["workflow_run"]["status"] == "RUNNING"
    assert len(provider.calls) == 3


def test_i037_accept_qa_warning_completes_without_new_model_and_is_idempotent(
    scope: Scope,
) -> None:
    qa = _challenged(_qa("PASS_WITH_WARNINGS"))
    qa["summary"] = "RAW_PROVIDER_OUTPUT_MUST_NOT_PERSIST"
    qa["validation_summary"] = "The bounded evidence passes with one verification warning."
    qa["acceptance_results"][0]["status"] = "NOT_VERIFIED"  # type: ignore[index]
    qa["acceptance_results"][0]["rationale"] = "The persisted evidence needs human confirmation."  # type: ignore[index]
    qa["regression_risks"] = ["The evidence binding should remain immutable."]
    qa["test_recommendations"] = ["Repeat the stale-preimage negative check."]
    qa["security_review_recommendations"] = ["Confirm the one-action approval binding."]
    qa["manual_review_recommendations"] = ["Inspect the safe persisted mutation metadata."]
    provider = QueueProvider([_manager(), _worker(), qa])
    created, advance = _create_vertical(scope, provider)
    for _ in range(3):
        waiting = _advance_fresh(provider, advance)
    assert waiting["outcome"] == "WAITING_FOR_HUMAN"
    run_id = str(created["workflow_run"]["id"])
    step_run_id = str(waiting["workflow_step_run_id"])
    url = _resolution_url(scope, run_id, step_run_id)
    payload = {"decision": "ACCEPT_RESULT", "reason": "Reviewed bounded QA warnings."}
    operator_url = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{run_id}/operator-view"
    )

    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        review = client.get(operator_url)
        accepted = client.post(url, json=payload)
        repeated = client.post(
            url,
            json={"decision": "ACCEPT_RESULT", "reason": "  Reviewed bounded QA warnings.  "},
        )
    assert accepted.status_code == repeated.status_code == 200
    assert review.status_code == 200
    active = next(item for item in review.json()["step_details"] if item["challenge"] is not None)
    safe_summary = active["challenge"]["safe_review_summary"]
    assert active["challenge"]["review_summary_status"] == "AVAILABLE"
    assert safe_summary["verdict"] == "PASS_WITH_WARNINGS"
    assert safe_summary["acceptance_results"] == [
        {
            "criterion_id": "criterion_01",
            "status": "NOT_VERIFIED",
            "rationale": "The persisted evidence needs human confirmation.",
            "evidence_references": [],
        }
    ]
    assert safe_summary["warnings"] == [
        {"category": "REGRESSION_RISK", "message": "The evidence binding should remain immutable."}
    ]
    assert [item["category"] for item in safe_summary["recommendations"]] == [
        "TEST",
        "SECURITY_REVIEW",
        "MANUAL_REVIEW",
    ]
    assert "RAW_PROVIDER_OUTPUT_MUST_NOT_PERSIST" not in json.dumps(review.json())
    assert accepted.json() == repeated.json()
    assert accepted.json()["outcome"] == "WORKFLOW_COMPLETED"
    assert accepted.json()["workflow_status"] == "COMPLETED"
    assert accepted.json()["step_status"] == "COMPLETED"
    assert len(provider.calls) == 3

    state = asyncio.run(_vertical_state(scope, UUID(run_id)))
    assert state["run"].status == "COMPLETED"  # type: ignore[union-attr]
    assert len(state["agent_runs"]) == len(state["model_runs"]) == 3
    assert state["approval_count"] == 0
    resolutions = state["resolutions"]
    assert len(resolutions) == 1
    assert resolutions[0].decision == "ACCEPT_RESULT"
    assert resolutions[0].decision_actor_type == "local_user"
    assert resolutions[0].qa_verdict == "PASS_WITH_WARNINGS"
    assert resolutions[0].safe_review_summary == safe_summary

    async def review_summary_is_immutable() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                with pytest.raises(IntegrityError, match="safe human review summary is immutable"):
                    await session.execute(
                        update(AgentChallengeResolution)
                        .where(AgentChallengeResolution.id == resolutions[0].id)
                        .values(safe_review_summary={"schema_version": 1})
                    )
                    await session.commit()
        finally:
            await database.dispose()

    asyncio.run(review_summary_is_immutable())
    events = [item for item in state["events"] if item.event_type == "workflow.challenge.resolved"]
    assert len(events) == 1
    resolution_audits = [
        item for item in state["audits"] if item.action == "workflow.challenge.resolve"
    ]
    assert len(resolution_audits) == 1
    assert resolution_audits[0].actor_type == "local_user"
    assert resolution_audits[0].metadata_json["reason_supplied"] is True
    assert events[0].payload == {
        "agent_run_id": str(resolutions[0].agent_run_id),
        "challenge_level": "HUMAN_REVIEW_RECOMMENDED",
        "decision": "ACCEPT_RESULT",
        "decision_actor_type": "local_user",
        "qa_verdict": "PASS_WITH_WARNINGS",
        "specialization_role": "qa_worker",
        "step_status": "RUNNING",
        "workflow_run_id": run_id,
        "workflow_status": "RUNNING",
        "workflow_step_run_id": step_run_id,
    }
    serialized = json.dumps([item.payload for item in state["events"]], sort_keys=True)
    assert "Reviewed bounded QA warnings" not in serialized


def test_i037_reject_is_terminal_and_conflicting_decision_is_rejected(scope: Scope) -> None:
    provider = QueueProvider([_challenged(_manager())])
    created, advance = _create_vertical(scope, provider)
    waiting = _advance_fresh(provider, advance)
    url = _resolution_url(
        scope,
        str(created["workflow_run"]["id"]),
        str(waiting["workflow_step_run_id"]),
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        rejected = client.post(url, json={"decision": "REJECT_RESULT"})
        conflict = client.post(url, json={"decision": "ACCEPT_RESULT"})
    assert rejected.status_code == 200
    assert rejected.json()["outcome"] == "WORKFLOW_FAILED"
    assert rejected.json()["reason_code"] == "agent_challenge_rejected"
    assert conflict.status_code == 409
    assert len(provider.calls) == 1


def test_i037_simultaneous_identical_resolution_has_one_authoritative_record(
    scope: Scope,
) -> None:
    provider = QueueProvider([_challenged(_manager())])
    created, advance = _create_vertical(scope, provider)
    waiting = _advance_fresh(provider, advance)
    run_id = str(created["workflow_run"]["id"])
    url = _resolution_url(scope, run_id, str(waiting["workflow_step_run_id"]))

    def submit() -> tuple[int, dict[str, object]]:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            response = client.post(url, json={"decision": "ACCEPT_RESULT"})
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: submit(), range(2)))
    assert [status for status, _ in responses] == [200, 200]
    assert responses[0][1] == responses[1][1]
    state = asyncio.run(_vertical_state(scope, UUID(run_id)))
    assert len(state["resolutions"]) == 1
    assert (
        len([item for item in state["events"] if item.event_type == "workflow.challenge.resolved"])
        == 1
    )
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("verdict", "reason_code"),
    [("FAIL", "qa_failed"), ("INCONCLUSIVE", "qa_inconclusive")],
)
def test_i037_acceptance_never_rewrites_negative_qa_verdict(
    scope: Scope, verdict: str, reason_code: str
) -> None:
    provider = QueueProvider([_manager(), _worker(), _challenged(_qa(verdict))])
    created, advance = _create_vertical(scope, provider)
    for _ in range(3):
        waiting = _advance_fresh(provider, advance)
    url = _resolution_url(
        scope,
        str(created["workflow_run"]["id"]),
        str(waiting["workflow_step_run_id"]),
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.post(url, json={"decision": "ACCEPT_RESULT"})
    assert response.status_code == 200
    assert response.json()["outcome"] == "WORKFLOW_FAILED"
    assert response.json()["reason_code"] == reason_code
    assert len(provider.calls) == 3


def test_i037_block_recommended_cannot_be_accepted_and_can_be_rejected(scope: Scope) -> None:
    challenged = _manager() | {
        "challenge": {
            "level": "BLOCK_RECOMMENDED",
            "reason": "Continuation is unsafe without rejection.",
            "evidence_source_references": [],
            "suggested_action": "Reject the result.",
        }
    }
    provider = QueueProvider([challenged])
    created, advance = _create_vertical(scope, provider)
    waiting = _advance_fresh(provider, advance)
    url = _resolution_url(
        scope,
        str(created["workflow_run"]["id"]),
        str(waiting["workflow_step_run_id"]),
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        blocked = client.post(url, json={"decision": "ACCEPT_RESULT"})
        rejected = client.post(url, json={"decision": "REJECT_RESULT"})
    assert blocked.status_code == 409
    assert rejected.status_code == 200
    assert rejected.json()["outcome"] == "WORKFLOW_FAILED"


def test_i037_caller_cannot_forge_human_authority_or_cross_scope(scope: Scope) -> None:
    provider = QueueProvider([_challenged(_manager())])
    created, advance = _create_vertical(scope, provider)
    waiting = _advance_fresh(provider, advance)
    run_id = str(created["workflow_run"]["id"])
    step_run_id = str(waiting["workflow_step_run_id"])
    url = _resolution_url(scope, run_id, step_run_id)
    other_scope_url = url.replace(str(scope.tenant_id), str(uuid4()), 1)
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        forged = client.post(
            url,
            json={"decision": "ACCEPT_RESULT", "decision_actor_type": "model"},
        )
        missing = client.post(other_scope_url, json={"decision": "ACCEPT_RESULT"})
    assert forged.status_code == 422
    assert missing.status_code == 404
    state = asyncio.run(_vertical_state(scope, UUID(run_id)))
    assert state["resolutions"][0].decision is None


def test_i037_policy_block_prevents_resolution(scope: Scope) -> None:
    async def add_block() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                await policy_service.create_rule(
                    session,
                    data=PolicyRuleCreate(
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        name="Block challenge resolution",
                        action_pattern="workflow.challenge.resolve",
                        effect=PolicyEffect.BLOCK,
                        actor_type="local_user",
                        resource_type="task",
                    ),
                )
        finally:
            await database.dispose()

    asyncio.run(add_block())
    provider = QueueProvider([_challenged(_manager())])
    created, advance = _create_vertical(scope, provider)
    waiting = _advance_fresh(provider, advance)
    url = _resolution_url(
        scope,
        str(created["workflow_run"]["id"]),
        str(waiting["workflow_step_run_id"]),
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.post(url, json={"decision": "REJECT_RESULT"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "challenge_resolution_policy_blocked"
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))
    assert state["run"].status == "RUNNING"  # type: ignore[union-attr]
    assert state["resolutions"][0].decision is None


@pytest.mark.parametrize(
    ("status", "failure_code"),
    [("BLOCKED", "agent_result_blocked"), ("NEEDS_INPUT", "agent_result_needs_input")],
)
def test_i037_blocked_or_needs_input_result_never_creates_resolvable_challenge(
    scope: Scope, status: str, failure_code: str
) -> None:
    result = _challenged(_manager()) | {"status": status}
    provider = QueueProvider([result])
    created, advance = _create_vertical(scope, provider)
    failed = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))
    assert failed["outcome"] == "WORKFLOW_FAILED"
    assert failed["reason_code"] == failure_code
    assert state["resolutions"] == []


def test_i029_malformed_manager_result_fails_without_downstream_handoff(scope: Scope) -> None:
    provider = QueueProvider([{"bad": "result"}])
    created, advance = _create_vertical(scope, provider)
    result = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))
    assert result["outcome"] == "WORKFLOW_FAILED"
    assert result["reason_code"] == "invalid_agent_result"
    assert [item.handoff_type for item in state["handoffs"]] == ["DEVELOPMENT_REQUEST"]
    assert len(state["agent_runs"]) == 1
    assert len(state["model_runs"]) == len(provider.calls) == 2


def test_i029_contextually_incompatible_manager_result_fails_before_handoff(
    scope: Scope,
) -> None:
    invalid = json.loads(json.dumps(_manager()))
    invalid["development_plan"]["proposed_tasks"].append(
        {
            "task_key": "second_assignment",
            "title": "Implement the second assignment",
            "objective": "Implement the second bounded task.",
            "required_capabilities": ["software_implementation"],
            "depends_on": [],
            "expected_output": "development.implementation_result",
            "acceptance_criteria": ["The second behavior is represented."],
            "risk_level": "LOW",
        }
    )
    provider = QueueProvider([invalid, invalid])
    created, advance = _create_vertical(scope, provider)
    result = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))

    assert result["outcome"] == "WORKFLOW_FAILED"
    assert result["reason_code"] == "invalid_agent_result"
    assert [item.handoff_type for item in state["handoffs"]] == ["DEVELOPMENT_REQUEST"]
    assert len(state["agent_runs"]) == 1
    assert len(state["model_runs"]) == len(provider.calls) == 2


def test_i029_tampered_handoff_prevents_downstream_model(scope: Scope) -> None:
    provider = QueueProvider([_manager()])
    created, advance = _create_vertical(scope, provider)
    _advance_fresh(provider, advance)
    run_id = UUID(str(created["workflow_run"]["id"]))

    async def tamper() -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory.begin() as session:
                handoff = await session.scalar(
                    select(WorkflowStepHandoff).where(
                        WorkflowStepHandoff.workflow_run_id == run_id,
                        WorkflowStepHandoff.handoff_type == "MANAGER_ASSIGNMENT",
                    )
                )
                assert handoff is not None
                handoff.handoff_type = "DEVELOPMENT_REQUEST"
        finally:
            await database.dispose()

    asyncio.run(tamper())
    result = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, run_id))
    assert result["reason_code"] == "workflow_handoff_invalid"
    assert len(state["agent_runs"]) == len(state["model_runs"]) == len(provider.calls) == 1
    assert [row[0].status for row in state["rows"]] == ["COMPLETED", "FAILED", "PENDING"]


def test_i029_double_advance_and_terminal_advance_do_not_duplicate_usage(scope: Scope) -> None:
    provider = SlowQueueProvider([_manager(), _worker(), _qa("PASS")])
    created, advance = _create_vertical(scope, provider)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: _advance_fresh(provider, advance), range(2)))
    assert {item["reason_code"] for item in responses} <= {
        None,
        "workflow_start_conflict",
        "step_claim_conflict",
    }
    assert len(provider.calls) == 1
    _advance_fresh(provider, advance)
    _advance_fresh(provider, advance)
    terminal = _advance_fresh(provider, advance)
    state = asyncio.run(_vertical_state(scope, UUID(str(created["workflow_run"]["id"]))))
    assert terminal["reason_code"] == "workflow_already_completed"
    assert len(provider.calls) == len(state["agent_runs"]) == len(state["model_runs"]) == 3
    assert len(state["handoffs"]) == 3
