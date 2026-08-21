import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
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
            await session.execute(delete(AgentRun).where(AgentRun.tenant_id == scope.tenant_id))
            await session.execute(delete(ModelRun).where(ModelRun.tenant_id == scope.tenant_id))
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
