import asyncio
import json
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
from novalton_api.modules.developer_manager.service import (
    DEVELOPER_MANAGER_CAPABILITIES,
    DEVELOPER_MANAGER_CATEGORY,
    DEVELOPER_MANAGER_MISSION,
    DEVELOPER_MANAGER_NAME,
    DEVELOPER_MANAGER_SLUG,
)
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workflows.models import WorkflowPlan, WorkflowRun
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    foreign_workspace_id: UUID
    project_id: UUID
    task_id: UUID
    definition_id: UUID
    foreign_definition_id: UUID
    model_id: UUID


def _result(*, challenge: str = "WARNING") -> str:
    reason = "Requirements need confirmation" if challenge != "NONE" else None
    return json.dumps(
        {
            "status": "COMPLETED",
            "summary": "Bounded development proposal",
            "findings": [],
            "artifacts": [],
            "sources": [],
            "assumptions": [{"statement": "Existing APIs remain stable", "source_references": []}],
            "risks": [],
            "uncertainties": [],
            "blocking_issues": [],
            "challenge": {
                "level": challenge,
                "reason": reason,
                "evidence_source_references": [],
                "suggested_action": "Confirm scope" if reason else None,
            },
            "recommended_next_steps": [],
            "requested_actions": [],
            "development_plan": {
                "objective_interpretation": "Implement a bounded backend change.",
                "architecture_workstreams": ["Validation", "API"],
                "proposed_tasks": [
                    {
                        "task_key": "verify",
                        "title": "Verify behavior",
                        "objective": "Verify the bounded implementation.",
                        "required_capabilities": ["testing"],
                        "depends_on": ["implement"],
                        "expected_output": "verification.report",
                        "acceptance_criteria": ["Focused tests pass"],
                        "risk_level": "LOW",
                    },
                    {
                        "task_key": "implement",
                        "title": "Implement change",
                        "objective": "Produce the bounded implementation.",
                        "required_capabilities": ["coding"],
                        "depends_on": [],
                        "expected_output": "implementation.change",
                        "acceptance_criteria": ["Contract is satisfied"],
                        "risk_level": "MEDIUM",
                    },
                ],
                "qa_review": "RECOMMENDED",
                "security_review": "RECOMMENDED",
                "manual_review": "REQUIRED",
            },
        }
    )


class MockProvider:
    provider_id = "mock"

    def __init__(self, content: str = _result()) -> None:
        self.content = content
        self.calls: list[GenerationRequest] = []

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        return GenerationResult(
            provider_id=self.provider_id,
            model_id=request.model_id,
            content=self.content,
            input_tokens=50,
            output_tokens=25,
            total_tokens=75,
            duration_ms=2,
        )


async def _seed(*, status: str = "ENABLED") -> Scope:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Manager", slug=f"manager-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Manager", slug="manager")
            foreign_workspace = Workspace(tenant_id=tenant.id, name="Foreign", slug="foreign")
            session.add_all((workspace, foreign_workspace))
            await session.flush()
            project = Project(workspace_id=workspace.id, name="Manager", slug="manager")
            session.add(project)
            await session.flush()
            task = Task(project_id=project.id, title="Plan")
            definition = AgentDefinition(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                name=DEVELOPER_MANAGER_NAME,
                slug=DEVELOPER_MANAGER_SLUG,
                version=1,
                status=status,
                category=DEVELOPER_MANAGER_CATEGORY,
                mission=DEVELOPER_MANAGER_MISSION,
                capabilities=DEVELOPER_MANAGER_CAPABILITIES,
                permissions=[],
            )
            foreign_definition = AgentDefinition(
                tenant_id=tenant.id,
                workspace_id=foreign_workspace.id,
                name=DEVELOPER_MANAGER_NAME,
                slug=DEVELOPER_MANAGER_SLUG,
                version=2,
                status="ENABLED",
                category=DEVELOPER_MANAGER_CATEGORY,
                mission=DEVELOPER_MANAGER_MISSION,
                capabilities=DEVELOPER_MANAGER_CAPABILITIES,
                permissions=[],
            )
            model = ModelDefinition(
                provider_id="mock",
                provider_model_id=f"manager-{uuid4().hex}",
                display_name="Manager model",
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
            session.add_all((task, definition, foreign_definition, model))
            await session.flush()
            return Scope(
                tenant.id,
                workspace.id,
                foreign_workspace.id,
                project.id,
                task.id,
                definition.id,
                foreign_definition.id,
                model.id,
            )
    finally:
        await database.dispose()


async def _cleanup(scope: Scope) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(
                delete(AuditRecord).where(AuditRecord.tenant_id == scope.tenant_id)
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
            await session.execute(delete(Workspace).where(Workspace.tenant_id == scope.tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == scope.tenant_id))
            await session.execute(
                delete(ModelDefinition).where(ModelDefinition.id == scope.model_id)
            )
    finally:
        await database.dispose()


def _input(scope: Scope) -> dict[str, object]:
    return {
        "objective": "Plan the bounded change",
        "constraints": ["No execution"],
        "project_id": str(scope.project_id),
        "task_id": str(scope.task_id),
        "expected_output_type": "development.plan_proposal",
        "permitted_tools": [],
        "model_requirements": {
            "required_capabilities": ["coding", "reasoning"],
            "structured_output_required": True,
            "tool_calling_required": False,
        },
    }


def _url(scope: Scope, *, workspace_id: UUID | None = None) -> str:
    return (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{workspace_id or scope.workspace_id}"
        "/developer-manager/plan"
    )


def test_manager_executes_once_and_only_returns_a_validated_proposal() -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider()
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            response = client.post(_url(scope), json=_input(scope))
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "SUCCEEDED"
        assert body["agent_definition_id"] == str(scope.definition_id)
        assert body["agent_definition_version"] == 1
        assert body["result"]["challenge"]["level"] == "WARNING"
        assert [
            task["task_key"] for task in body["result"]["development_plan"]["proposed_tasks"]
        ] == ["implement", "verify"]
        assert len(provider.calls) == 1
        request = provider.calls[0]
        assert "tools" not in request.model_dump()
        assert "no tools" in request.messages[0].content.lower()
        instructions = request.messages[0].content
        assert "the plan grants no tool permission or execution authority" in instructions
        assert "human approval does not by itself mean the objective is BLOCKED" in instructions
        assert "deterministic permission checks, policy evaluation" in instructions.lower()

        async def counts() -> tuple[int, int, int, int, int, int]:
            database = Database.from_settings(Settings())
            try:
                async with database.session_factory() as session:
                    models = (
                        AgentRun,
                        ModelRun,
                        WorkflowPlan,
                        WorkflowRun,
                        ApprovalRequest,
                        PolicyRule,
                    )
                    counts = []
                    for model in models:
                        statement = (
                            select(func.count())
                            .select_from(model)
                            .where(model.tenant_id == scope.tenant_id)
                        )
                        counts.append(int(await session.scalar(statement) or 0))
                    return tuple(counts)  # type: ignore[return-value]
            finally:
                await database.dispose()

        assert asyncio.run(counts()) == (1, 1, 0, 0, 0, 0)
    finally:
        asyncio.run(_cleanup(scope))


@pytest.mark.parametrize(
    ("content", "call_count"),
    [
        ("not-json", 1),
        (
            _result().replace(
                '"requested_actions": []',
                '"requested_actions": [{"action_type":"git.push"}]',
            ),
            2,
        ),
    ],
)
def test_manager_rejects_invalid_provider_results_without_retry(
    content: str, call_count: int
) -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider(content)
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            response = client.post(_url(scope), json=_input(scope))
        assert response.status_code == 200
        assert response.json()["status"] == "FAILED"
        assert response.json()["result"] is None
        assert len(provider.calls) == call_count
    finally:
        asyncio.run(_cleanup(scope))


def test_manager_rejects_disabled_and_foreign_scope_definitions_safely() -> None:
    disabled = asyncio.run(_seed(status="DISABLED"))
    provider = MockProvider()
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            disabled_response = client.post(_url(disabled), json=_input(disabled))
            foreign_response = client.post(
                _url(disabled, workspace_id=disabled.foreign_workspace_id),
                json=_input(disabled),
            )
        assert disabled_response.status_code == 409
        assert disabled_response.json()["error"]["code"] == "developer_manager_unavailable"
        assert foreign_response.status_code == 404
        assert provider.calls == []
    finally:
        asyncio.run(_cleanup(disabled))


def test_manager_request_rejects_tools_and_provider_overrides_before_execution() -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider()
    value = _input(scope)
    value.update(permitted_tools=["shell"], provider_url="https://unsafe.example")
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            response = client.post(_url(scope), json=value)
        assert response.status_code == 422
        assert provider.calls == []
    finally:
        asyncio.run(_cleanup(scope))


def test_manager_human_approval_objective_is_not_mechanically_blocked() -> None:
    scope = asyncio.run(_seed())
    provider = MockProvider(_result(challenge="NONE"))
    value = _input(scope)
    value["objective"] = (
        "Plan one bounded workspace mutation assignment. The downstream mutation requires "
        "deterministic Policy evaluation and explicit human approval before execution."
    )
    try:
        with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
            response = client.post(_url(scope), json=value)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "SUCCEEDED"
        assert body["result"]["status"] == "COMPLETED"
        assert body["result"]["challenge"]["level"] == "NONE"
        assert len(provider.calls) == 1
        provider_input = json.loads(provider.calls[0].messages[1].content)["agent_input"]
        assert provider_input["permitted_tools"] == []
        assert provider_input["model_requirements"]["tool_calling_required"] is False
    finally:
        asyncio.run(_cleanup(scope))
