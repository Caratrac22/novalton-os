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
from novalton_api.infrastructure.providers.errors import ProviderError, ProviderFailure
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.agents import service as agent_service
from novalton_api.modules.agents.contracts import AgentResult, AgentResultStatus, ChallengeLevel
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import AgentExecutionResponse, AgentRunCreate
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.orchestrator import service as orchestrator_service
from novalton_api.modules.policy.schemas import RiskLevel
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workflows import service as workflow_service
from novalton_api.modules.workflows.models import (
    WorkflowPlan,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
    WorkflowStepRun,
)
from novalton_api.modules.workflows.schemas import WorkflowPlanCreate
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    definition_id: UUID
    model_id: UUID


class MockProvider:
    provider_id = "mock"

    def __init__(self, content: str, failure: ProviderFailure | None = None) -> None:
        self.content = content
        self.failure = failure
        self.calls: list[GenerationRequest] = []

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        if self.failure is not None:
            raise ProviderError(self.failure, provider_id=self.provider_id)
        return GenerationResult(
            provider_id=self.provider_id,
            model_id=request.model_id,
            content=self.content,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            duration_ms=1,
        )


def _result(*, status: str = "COMPLETED", challenge: str = "NONE") -> AgentResult:
    reason = "Human decision required" if challenge != "NONE" else None
    return AgentResult.model_validate(
        {
            "status": AgentResultStatus(status),
            "summary": "Safe result",
            "findings": [],
            "artifacts": [],
            "sources": [],
            "assumptions": [],
            "risks": [],
            "uncertainties": [],
            "blocking_issues": [],
            "challenge": {
                "level": ChallengeLevel(challenge),
                "reason": reason,
                "evidence_source_references": [],
                "suggested_action": None,
            },
            "recommended_next_steps": [],
            "requested_actions": [
                {
                    "action_type": "git.write_file",
                    "target_reference": "proposal-only",
                    "reason": "Must not execute",
                    "risk_hint": RiskLevel.LOW,
                }
            ],
        }
    )


async def _seed() -> Scope:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Orchestrator", slug=f"orchestrator-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Orchestrator", slug="orchestrator")
            session.add(workspace)
            await session.flush()
            project = Project(workspace_id=workspace.id, name="Orchestrator", slug="orchestrator")
            session.add(project)
            await session.flush()
            task = Task(project_id=project.id, title="Orchestrate")
            definition = AgentDefinition(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                name="Exact Worker",
                slug="exact_worker",
                version=1,
                status="ENABLED",
                category="review",
                mission="Return a bounded result.",
                capabilities=["reasoning"],
                permissions=[],
            )
            model = ModelDefinition(
                provider_id="mock",
                provider_model_id=f"orchestrator-{uuid4().hex}",
                display_name="Orchestrator test model",
                status="AVAILABLE",
                context_window=128_000,
                reasoning=True,
                coding=False,
                tool_calling=False,
                structured_output=True,
                vision=False,
                input_price_per_million=Decimal("1"),
                output_price_per_million=Decimal("1"),
                currency="USD",
                free_allowlisted=False,
            )
            session.add_all((task, definition, model))
            await session.flush()
            return Scope(tenant.id, workspace.id, project.id, task.id, definition.id, model.id)
    finally:
        await database.dispose()


async def _cleanup(scope: Scope) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(
                delete(RuntimeEvent).where(RuntimeEvent.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(AuditRecord).where(AuditRecord.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(WorkflowStepRun).where(
                    WorkflowStepRun.workflow_run_id.in_(
                        select(WorkflowRun.id).where(WorkflowRun.tenant_id == scope.tenant_id)
                    )
                )
            )
            await session.execute(
                delete(WorkflowRun).where(WorkflowRun.tenant_id == scope.tenant_id)
            )
            await session.execute(
                delete(WorkflowStepDependency).where(
                    WorkflowStepDependency.workflow_plan_id.in_(
                        select(WorkflowPlan.id).where(WorkflowPlan.tenant_id == scope.tenant_id)
                    )
                )
            )
            await session.execute(
                delete(WorkflowStep).where(
                    WorkflowStep.workflow_plan_id.in_(
                        select(WorkflowPlan.id).where(WorkflowPlan.tenant_id == scope.tenant_id)
                    )
                )
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
                delete(AgentDefinition).where(AgentDefinition.id == scope.definition_id)
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


async def _run(scope: Scope, steps: list[dict[str, object]]) -> UUID:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            plan = await workflow_service.create_plan(
                session,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                task_id=scope.task_id,
                data=WorkflowPlanCreate(title="Deterministic plan", steps=steps),
            )
            run = await workflow_service.create_run(
                session,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                plan_id=plan.id,
            )
            return run.id
    finally:
        await database.dispose()


def _agent_step(
    scope: Scope, key: str, *, depends_on: list[str] | None = None
) -> dict[str, object]:
    return {
        "step_key": key,
        "title": f"Execute {key}",
        "step_type": "AGENT_TASK",
        "assigned_capability": "reasoning",
        "agent_definition_id": scope.definition_id,
        "depends_on": depends_on or [],
    }


def _url(scope: Scope, run_id: UUID) -> str:
    return (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/workflow-runs/{run_id}/advance"
    )


def _fake_execution(monkeypatch: pytest.MonkeyPatch, result: AgentResult) -> list[UUID]:
    calls: list[UUID] = []

    async def execute(session: object, **kwargs: object) -> AgentExecutionResponse:
        definition_id = kwargs["definition_id"]
        calls.append(definition_id)  # type: ignore[arg-type]
        data = kwargs["data"]
        run = await agent_service.create_run(
            session,  # type: ignore[arg-type]
            tenant_id=kwargs["tenant_id"],  # type: ignore[arg-type]
            workspace_id=kwargs["workspace_id"],  # type: ignore[arg-type]
            data=AgentRunCreate(
                agent_definition_id=definition_id,  # type: ignore[arg-type]
                project_id=UUID(data.project_id),  # type: ignore[union-attr]
                task_id=UUID(data.task_id),  # type: ignore[union-attr]
            ),
        )
        run = await agent_service.start_run(
            session,  # type: ignore[arg-type]
            tenant_id=kwargs["tenant_id"],  # type: ignore[arg-type]
            workspace_id=kwargs["workspace_id"],  # type: ignore[arg-type]
            run_id=run.id,
        )
        if result.status in {"COMPLETED", "PARTIAL"}:
            run = await agent_service.succeed_run(
                session,  # type: ignore[arg-type]
                tenant_id=kwargs["tenant_id"],  # type: ignore[arg-type]
                workspace_id=kwargs["workspace_id"],  # type: ignore[arg-type]
                run_id=run.id,
            )
            error_code = None
        else:
            run = await agent_service.fail_run(
                session,  # type: ignore[arg-type]
                tenant_id=kwargs["tenant_id"],  # type: ignore[arg-type]
                workspace_id=kwargs["workspace_id"],  # type: ignore[arg-type]
                run_id=run.id,
                failure_code=f"agent_result_{result.status.value.lower()}",
            )
            error_code = run.failure_code
        return AgentExecutionResponse(
            agent_run_id=run.id,
            agent_definition_id=definition_id,  # type: ignore[arg-type]
            agent_definition_version=1,
            status=run.status,
            result=result,
            error_code=error_code,
        )

    monkeypatch.setattr(orchestrator_service.agent_execution, "execute", execute)
    return calls


def test_one_step_per_advance_is_deterministic_and_unlocks_dependencies(
    scope: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = asyncio.run(
        _run(
            scope,
            [
                _agent_step(scope, "zeta"),
                _agent_step(scope, "alpha"),
                _agent_step(scope, "last", depends_on=["zeta", "alpha"]),
            ],
        )
    )
    calls = _fake_execution(monkeypatch, _result())
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        first = client.post(_url(scope, run_id)).json()
        second = client.post(_url(scope, run_id)).json()
        third = client.post(_url(scope, run_id)).json()
        terminal = client.post(_url(scope, run_id)).json()
    assert [first["step_key"], second["step_key"], third["step_key"]] == ["zeta", "alpha", "last"]
    assert [first["outcome"], second["outcome"], third["outcome"]] == [
        "STEP_COMPLETED",
        "STEP_COMPLETED",
        "WORKFLOW_COMPLETED",
    ]
    assert terminal["outcome"] == "WORKFLOW_COMPLETED"
    assert calls == [scope.definition_id, scope.definition_id, scope.definition_id]


@pytest.mark.parametrize(
    ("step_type", "reason"),
    [("MANUAL_REVIEW", "manual_review_required"), ("SYSTEM", "unsupported_system_step")],
)
def test_non_executable_steps_wait_without_agent_call(
    scope: Scope, monkeypatch: pytest.MonkeyPatch, step_type: str, reason: str
) -> None:
    run_id = asyncio.run(
        _run(
            scope, [{"step_key": "wait", "title": "Wait", "step_type": step_type, "depends_on": []}]
        )
    )
    calls = _fake_execution(monkeypatch, _result())
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        body = client.post(_url(scope, run_id)).json()
    assert (body["outcome"], body["workflow_status"], body["step_status"]) == (
        "WAITING_FOR_HUMAN",
        "RUNNING",
        "READY",
    )
    assert body["reason_code"] == reason
    assert calls == []


@pytest.mark.parametrize("challenge", ["HUMAN_REVIEW_RECOMMENDED", "BLOCK_RECOMMENDED"])
def test_meaningful_challenge_is_persistently_stopped_and_surfaced(
    scope: Scope, monkeypatch: pytest.MonkeyPatch, challenge: str
) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "review")]))
    calls = _fake_execution(monkeypatch, _result(challenge=challenge))
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        first = client.post(_url(scope, run_id)).json()
        second = client.post(_url(scope, run_id)).json()
    assert first["outcome"] == "WAITING_FOR_HUMAN"
    assert first["challenge_level"] == challenge
    assert second["outcome"] == "WAITING_FOR_HUMAN"
    assert first["agent_run_id"] == second["agent_run_id"]
    assert calls == [scope.definition_id]


@pytest.mark.parametrize("status", ["FAILED", "BLOCKED", "NEEDS_INPUT"])
def test_unsuccessful_agent_result_fails_step_and_workflow(
    scope: Scope, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "failure")]))
    _fake_execution(monkeypatch, _result(status=status))
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        body = client.post(_url(scope, run_id)).json()
    assert (body["outcome"], body["workflow_status"], body["step_status"]) == (
        "WORKFLOW_FAILED",
        "FAILED",
        "FAILED",
    )
    assert body["reason_code"] == f"agent_result_{status.lower()}"


def test_safe_runtime_events_and_no_orchestrator_agent_definition(
    scope: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "only")]))
    _fake_execution(monkeypatch, _result())
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        assert client.post(_url(scope, run_id)).status_code == 200

    async def inspect() -> tuple[list[str], list[dict[str, object] | None], int]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                events = list(
                    await session.scalars(
                        select(RuntimeEvent)
                        .where(RuntimeEvent.tenant_id == scope.tenant_id)
                        .order_by(RuntimeEvent.occurred_at, RuntimeEvent.id)
                    )
                )
                orchestrators = await session.scalar(
                    select(func.count())
                    .select_from(AgentDefinition)
                    .where(AgentDefinition.slug == "orchestrator")
                )
                return (
                    [event.event_type for event in events],
                    [event.payload for event in events],
                    int(orchestrators or 0),
                )
        finally:
            await database.dispose()

    event_types, payloads, orchestrators = asyncio.run(inspect())
    assert event_types == [
        "workflow.run.started",
        "workflow.step.started",
        "workflow.step.completed",
        "workflow.run.completed",
    ]
    assert orchestrators == 0
    assert all(
        payload is not None and "summary" not in payload and "requested_actions" not in payload
        for payload in payloads
    )


def test_foreign_scope_is_sanitized_before_execution(
    scope: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "only")]))
    calls = _fake_execution(monkeypatch, _result())
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        response = client.post(
            f"/api/v1/tenants/{uuid4()}/workspaces/{scope.workspace_id}/workflow-runs/{run_id}/advance"
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"
    assert calls == []


def test_advance_rejects_client_execution_payload(
    scope: Scope, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "only")]))
    calls = _fake_execution(monkeypatch, _result())
    with TestClient(create_app(provider_registry=ProviderRegistry(()))) as client:
        response = client.post(
            _url(scope, run_id),
            json={"agent_definition_id": str(uuid4()), "provider_url": "https://example.com"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_orchestration_request"
    assert calls == []


def test_real_i022_path_executes_once_links_and_ignores_requested_actions(scope: Scope) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "real")]))
    provider = MockProvider(_result().model_dump_json())
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        body = client.post(_url(scope, run_id)).json()
    assert body["outcome"] == "WORKFLOW_COMPLETED"
    assert len(provider.calls) == 1
    assert provider.calls[0].model_id.startswith("orchestrator-")
    assert "tools" not in provider.calls[0].model_dump()

    async def inspect() -> tuple[UUID | None, int]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                step_run = await session.scalar(
                    select(WorkflowStepRun).where(WorkflowStepRun.workflow_run_id == run_id)
                )
                count = await session.scalar(
                    select(func.count())
                    .select_from(ModelRun)
                    .where(ModelRun.tenant_id == scope.tenant_id)
                )
                assert step_run is not None
                return step_run.agent_run_id, int(count or 0)
        finally:
            await database.dispose()

    linked_agent_run, model_runs = asyncio.run(inspect())
    assert linked_agent_run == UUID(body["agent_run_id"])
    assert model_runs == 1


@pytest.mark.parametrize(
    ("content", "failure_code", "call_count"),
    [
        ("not-json", "invalid_provider_json", 1),
        (json.dumps({"bad": "result"}), "invalid_agent_result", 2),
    ],
)
def test_real_i022_invalid_result_fails_without_retry(
    scope: Scope, content: str, failure_code: str, call_count: int
) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "invalid")]))
    provider = MockProvider(content)
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        body = client.post(_url(scope, run_id)).json()
    assert body["outcome"] == "WORKFLOW_FAILED"
    assert body["reason_code"] == failure_code
    assert len(provider.calls) == call_count


def test_real_i022_no_suitable_model_fails_without_provider_call(scope: Scope) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "unroutable")]))

    async def disable() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory.begin() as session:
                model = await session.get(ModelDefinition, scope.model_id)
                assert model is not None
                model.status = "UNAVAILABLE"
        finally:
            await database.dispose()

    asyncio.run(disable())
    provider = MockProvider(_result().model_dump_json())
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        body = client.post(_url(scope, run_id)).json()
    assert body["outcome"] == "WORKFLOW_FAILED"
    assert body["reason_code"] == "no_suitable_model"
    assert provider.calls == []


def test_simultaneous_advance_cannot_duplicate_agent_or_model_run(scope: Scope) -> None:
    run_id = asyncio.run(_run(scope, [_agent_step(scope, "concurrent")]))

    class SlowProvider(MockProvider):
        async def complete(self, request: GenerationRequest) -> GenerationResult:
            self.calls.append(request)
            await asyncio.sleep(0.25)
            return GenerationResult(
                provider_id=self.provider_id,
                model_id=request.model_id,
                content=self.content,
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                duration_ms=250,
            )

    provider = SlowProvider(_result().model_dump_json())
    with (
        TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        responses = list(executor.map(lambda _: client.post(_url(scope, run_id)), range(2)))
    assert all(response.status_code == 200 for response in responses), [
        response.text for response in responses
    ]
    assert len(provider.calls) == 1

    async def counts() -> tuple[int, int]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                agent_runs = await session.scalar(
                    select(func.count())
                    .select_from(AgentRun)
                    .where(AgentRun.tenant_id == scope.tenant_id)
                )
                model_runs = await session.scalar(
                    select(func.count())
                    .select_from(ModelRun)
                    .where(ModelRun.tenant_id == scope.tenant_id)
                )
                return int(agent_runs or 0), int(model_runs or 0)
        finally:
            await database.dispose()

    assert asyncio.run(counts()) == (1, 1)
