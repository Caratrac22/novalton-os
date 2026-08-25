import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.developer_manager import service as manager_service
from novalton_api.modules.developer_worker import service as developer_service
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.projects.models import Project
from novalton_api.modules.qa_worker import service as qa_service
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
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

    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results
        self.calls: list[GenerationRequest] = []

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        return GenerationResult(
            provider_id=self.provider_id,
            model_id=request.model_id,
            content=json.dumps(self.results.pop(0)),
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


async def _seed() -> Scope:
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
                    version=1,
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
                    permissions=[],
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
                delete(WorkflowStepHandoff).where(WorkflowStepHandoff.workflow_run_id.in_(run_ids))
            )
            await session.execute(
                delete(RuntimeEvent).where(RuntimeEvent.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(AuditRecord).where(AuditRecord.tenant_id == scope.tenant_id)
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
                "plan_count": plan_count,
                "workflow_run_count": workflow_run_count,
                "audit_count": audit_count,
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
    assert [item.agent_version for item in agent_runs] == [1, 1, 1]
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
    repeated = _advance_fresh(provider, advance)
    assert repeated["reason_code"] == "step_requires_intervention"
    assert len(provider.calls) == expected_runs


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
