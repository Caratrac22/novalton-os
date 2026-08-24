import asyncio
import json
from concurrent.futures import CancelledError as FutureCancelledError
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult
from novalton_api.infrastructure.providers.errors import (
    ProviderCancellationError,
    ProviderError,
    ProviderFailure,
)
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.agents.contracts import AgentInput, AgentResult
from novalton_api.modules.agents.execution import _generation_request
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_router import service as router_service
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    definition_id: UUID
    model_id: UUID


def _valid_result(**changes: object) -> str:
    value: dict[str, object] = {
        "status": "COMPLETED",
        "summary": "Bounded result",
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
    value.update(changes)
    return json.dumps(value)


class MockProvider:
    provider_id = "mock"

    def __init__(self, content: str = _valid_result(), failure: ProviderFailure | None = None):
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
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            provider_request_id="request-safe-1",
            duration_ms=12.5,
        )


async def _seed(*, model_available: bool = True, definition_status: str = "ENABLED") -> Scope:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Execution", slug=f"execution-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Execution", slug="execution")
            session.add(workspace)
            await session.flush()
            project = Project(workspace_id=workspace.id, name="Execution", slug="execution")
            session.add(project)
            await session.flush()
            task = Task(project_id=project.id, title="Execute")
            definition = AgentDefinition(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                name="Reviewer",
                slug="reviewer",
                version=1,
                status=definition_status,
                category="review",
                mission="Review the supplied bounded input.",
                capabilities=["reasoning"],
                permissions=[],
            )
            model = ModelDefinition(
                provider_id="mock",
                provider_model_id=f"model-{uuid4().hex}",
                display_name="Mock model",
                status="AVAILABLE" if model_available else "UNAVAILABLE",
                context_window=128_000,
                reasoning=True,
                coding=False,
                tool_calling=False,
                structured_output=True,
                vision=False,
                input_price_per_million=Decimal("1"),
                output_price_per_million=Decimal("2"),
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
            await session.execute(delete(AgentRun).where(AgentRun.tenant_id == scope.tenant_id))
            await session.execute(delete(ModelRun).where(ModelRun.tenant_id == scope.tenant_id))
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


def _input(scope: Scope) -> dict[str, object]:
    return {
        "objective": "Review this task",
        "constraints": ["Do not execute actions"],
        "project_id": str(scope.project_id),
        "task_id": str(scope.task_id),
        "context_references": [],
        "source_references": [],
        "prior_result_references": [],
        "expected_output_type": "review.report",
        "permitted_tools": [],
        "model_requirements": {
            "required_capabilities": ["reasoning"],
            "structured_output_required": True,
            "tool_calling_required": False,
        },
    }


def _url(scope: Scope) -> str:
    return (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/agents/{scope.definition_id}/run"
    )


def test_generation_request_propagates_strict_agent_result_schema() -> None:
    definition = AgentDefinition(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        name="Reviewer",
        slug="reviewer",
        version=1,
        status="ENABLED",
        category="review",
        mission="Review the supplied bounded input.",
        capabilities=["reasoning"],
        permissions=[],
    )
    data = AgentInput.model_validate(
        {
            "objective": "Review this task",
            "constraints": ["Do not execute actions"],
            "context_references": [],
            "source_references": [],
            "prior_result_references": [],
            "expected_output_type": "review.report",
            "permitted_tools": [],
        }
    )

    generation = _generation_request(definition, data, provider_model_id="model-1")

    assert generation.structured_output is not None
    assert generation.structured_output.name == "AgentResult"
    assert generation.structured_output.json_schema == AgentResult.model_json_schema()
    assert generation.structured_output.strict is True


def test_provider_backed_execution_captures_usage_and_linkage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider(
        _valid_result(
            requested_actions=[
                {
                    "action_type": "git.write_file",
                    "target_reference": "file-1",
                    "reason": "Proposal only",
                    "risk_hint": "LOW",
                }
            ]
        )
    )
    route_calls = 0
    original_route = router_service.simulate

    async def counted_route(*args: object, **kwargs: object):
        nonlocal route_calls
        route_calls += 1
        return await original_route(*args, **kwargs)

    monkeypatch.setattr(router_service, "simulate", counted_route)
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            response = client.post(_url(scope), json=_input(scope))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "SUCCEEDED"
        assert body["selected_model"] == {
            "catalog_model_id": str(scope.model_id),
            "provider_id": "mock",
            "provider_model_id": provider.calls[0].model_id,
        }
        assert len(provider.calls) == 1
        assert route_calls == 1
        assert len(provider.calls[0].messages) == 2
        assert "tools" not in provider.calls[0].model_dump()

        async def inspect() -> tuple[AgentRun, ModelRun, int, int]:
            database = Database.from_settings(Settings())
            try:
                async with database.session_factory() as session:
                    agent_run = await session.get(AgentRun, UUID(body["agent_run_id"]))
                    model_run = await session.get(ModelRun, UUID(body["model_run_id"]))
                    approvals = await session.scalar(
                        select(func.count()).select_from(ApprovalRequest)
                    )
                    policies = await session.scalar(select(func.count()).select_from(PolicyRule))
                    assert agent_run is not None and model_run is not None
                    return agent_run, model_run, approvals or 0, policies or 0
            finally:
                await database.dispose()

        agent_run, model_run, approvals, policies = asyncio.run(inspect())
        assert agent_run.model_run_id == model_run.id
        assert model_run.status == "SUCCEEDED"
        assert (model_run.input_tokens, model_run.output_tokens, model_run.actual_cost) == (
            100,
            20,
            Decimal("0.0001400000"),
        )
        assert "content" not in ModelRun.__table__.columns
        assert (approvals, policies) == (0, 0)
    finally:
        asyncio.run(_cleanup(scope))


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("not-json", "invalid_provider_json"),
        (_valid_result(extra="rejected"), "invalid_agent_result"),
    ],
)
def test_invalid_provider_output_fails_without_repair(content: str, code: str) -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider(content)
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            body = client.post(_url(scope), json=_input(scope)).json()
        assert (body["status"], body["error_code"], body["result"]) == ("FAILED", code, None)
        assert len(provider.calls) == 1
    finally:
        asyncio.run(_cleanup(scope))


@pytest.mark.parametrize(
    "failure", [failure for failure in ProviderFailure if failure != ProviderFailure.CANCELLATION]
)
def test_normalized_provider_failure_has_one_attempt(failure: ProviderFailure) -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider(failure=failure)
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            body = client.post(_url(scope), json=_input(scope)).json()
        assert body["status"] == "FAILED"
        assert body["error_code"] == f"provider_{failure.value}"
        assert len(provider.calls) == 1
    finally:
        asyncio.run(_cleanup(scope))


def test_cancellation_preserves_asyncio_semantics_and_cancels_both_runs() -> None:
    scope = asyncio.run(_seed())

    class CancellingProvider(MockProvider):
        async def complete(self, request: GenerationRequest) -> GenerationResult:
            self.calls.append(request)
            raise ProviderCancellationError(provider_id=self.provider_id)

    provider = CancellingProvider()
    try:
        with (
            TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client,
            pytest.raises((asyncio.CancelledError, FutureCancelledError)),
        ):
            client.post(_url(scope), json=_input(scope))
        assert len(provider.calls) == 1

        async def statuses() -> tuple[str, str]:
            database = Database.from_settings(Settings())
            try:
                async with database.session_factory() as session:
                    agent_status = await session.scalar(
                        select(AgentRun.status).where(AgentRun.tenant_id == scope.tenant_id)
                    )
                    model_status = await session.scalar(
                        select(ModelRun.status).where(ModelRun.tenant_id == scope.tenant_id)
                    )
                    assert agent_status is not None and model_status is not None
                    return agent_status, model_status
            finally:
                await database.dispose()

        assert asyncio.run(statuses()) == ("CANCELLED", "CANCELLED")
    finally:
        asyncio.run(_cleanup(scope))


def test_no_suitable_model_creates_no_model_run_and_makes_no_provider_call() -> None:
    scope = asyncio.run(_seed(model_available=False))
    provider = MockProvider()
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            body = client.post(_url(scope), json=_input(scope)).json()
        assert (body["status"], body["error_code"], body["model_run_id"]) == (
            "FAILED",
            "no_suitable_model",
            None,
        )
        assert provider.calls == []
    finally:
        asyncio.run(_cleanup(scope))


def test_disabled_and_foreign_definition_are_safely_rejected() -> None:
    scope = asyncio.run(_seed(definition_status="DISABLED"))
    provider = MockProvider()
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            assert client.post(_url(scope), json=_input(scope)).status_code == 409
            foreign = _url(scope).replace(str(scope.definition_id), str(uuid4()))
            assert client.post(foreign, json=_input(scope)).status_code == 404
        assert provider.calls == []
    finally:
        asyncio.run(_cleanup(scope))


def test_foreign_project_or_task_scope_is_rejected_before_execution() -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider()
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            foreign_project = _input(scope) | {"project_id": str(uuid4()), "task_id": None}
            foreign_task = _input(scope) | {"task_id": str(uuid4())}
            assert client.post(_url(scope), json=foreign_project).status_code == 404
            assert client.post(_url(scope), json=foreign_task).status_code == 404
        assert provider.calls == []
    finally:
        asyncio.run(_cleanup(scope))
