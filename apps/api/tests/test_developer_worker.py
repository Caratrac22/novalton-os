from types import SimpleNamespace
from uuid import uuid4

import pytest

from novalton_api.core.config import Settings  # noqa: F401 - initialize core imports first
from novalton_api.core.database import Database  # noqa: F401 - register ORM models first
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents.schemas import AgentExecutionResponse, AgentRunStatus
from novalton_api.modules.developer_worker import service
from novalton_api.modules.developer_worker.contracts import (
    DeveloperWorkerResult,
    DeveloperWorkerTerminalResult,
    DevelopmentAssignmentInput,
)
from novalton_api.modules.developer_worker.schemas import DeveloperWorkerExecutionRequest


def _result(*, status: str = "COMPLETED", challenge: str = "NONE") -> DeveloperWorkerResult:
    reason = "Scope is ambiguous." if challenge != "NONE" else None
    return DeveloperWorkerResult.model_validate_json(
        f"""{{
          "status":"{status}","summary":"Bounded result.","findings":[],"artifacts":[],
          "sources":[],"assumptions":[],"risks":[],"uncertainties":[],
          "blocking_issues":[],"challenge":{{"level":"{challenge}","reason":
          {f'"{reason}"' if reason else "null"},"evidence_source_references":[],
          "suggested_action":null}},"recommended_next_steps":[],"requested_actions":[],
          "task_interpretation":"Implement one bounded change.",
          "implementation_summary":"Propose a validated metadata-only change.",
          "changes":[{{"path":"apps/api/src/feature.py","kind":"MODIFY",
          "rationale":"Implement behavior.","expected_effect":"Satisfy acceptance.",
          "acceptance_criteria":["criterion_one"]}}],
          "acceptance_checks":[{{"criterion_id":"criterion_one","status":"SATISFIED",
          "detail":"Contract is satisfied."}}],"test_recommendations":["Run tests."],
          "blockers":[]}}
        """
    )


@pytest.mark.asyncio
async def test_worker_uses_specialized_i022_execution_exactly_once(monkeypatch) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    definition_id = uuid4()
    run_id = uuid4()
    definition = SimpleNamespace(
        id=definition_id,
        version=1,
        status="ENABLED",
        slug=service.DEVELOPER_WORKER_SLUG,
        category=service.DEVELOPER_WORKER_CATEGORY,
        permissions=[],
    )
    calls: list[dict[str, object]] = []

    async def latest_definition(session, **kwargs):
        assert kwargs == {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "slug": service.DEVELOPER_WORKER_SLUG,
            "exclude_archived": True,
        }
        return definition

    async def execute(session, **kwargs):
        calls.append(kwargs)
        return AgentExecutionResponse(
            agent_run_id=run_id,
            agent_definition_id=definition_id,
            agent_definition_version=1,
            status=AgentRunStatus.SUCCEEDED,
            result=_result(challenge="WARNING"),
        )

    monkeypatch.setattr(service.repository, "latest_definition", latest_definition)
    monkeypatch.setattr(service.execution, "execute", execute)
    data = DeveloperWorkerExecutionRequest(objective="Implement the bounded assignment.")
    response = await service.execute_assignment(
        object(),
        registry=object(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )

    assert len(calls) == 1
    assert calls[0]["definition_id"] == definition_id
    assert calls[0]["data"] is data
    assert calls[0]["result_contract"] is DeveloperWorkerResult
    assert calls[0]["continuation_result_contract"] is DeveloperWorkerTerminalResult
    assert response.status == AgentRunStatus.SUCCEEDED
    assert response.result is not None
    assert response.result.challenge.level.value == "WARNING"
    assert response.result.requested_actions == []


@pytest.mark.asyncio
async def test_worker_resolves_only_latest_same_scope_and_rejects_unavailable(monkeypatch) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    captured: list[dict[str, object]] = []

    async def missing(session, **kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr(service.repository, "latest_definition", missing)
    with pytest.raises(ApplicationError) as missing_error:
        await service.resolve_definition(object(), tenant_id=tenant_id, workspace_id=workspace_id)
    assert missing_error.value.code == "developer_worker_unavailable"
    assert captured == [
        {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "slug": service.DEVELOPER_WORKER_SLUG,
            "exclude_archived": True,
        }
    ]

    async def disabled(session, **kwargs):
        return SimpleNamespace(status="DISABLED")

    monkeypatch.setattr(service.repository, "latest_definition", disabled)
    with pytest.raises(ApplicationError) as disabled_error:
        await service.resolve_definition(object(), tenant_id=tenant_id, workspace_id=workspace_id)
    assert disabled_error.value.code == "developer_worker_unavailable"


def test_worker_definition_is_normal_governed_agent_metadata() -> None:
    assert service.DEVELOPER_WORKER_SLUG == "developer_worker"
    assert service.DEVELOPER_WORKER_CATEGORY == "development"
    assert sorted(service.DEVELOPER_WORKER_CAPABILITIES) == service.DEVELOPER_WORKER_CAPABILITIES
    assert "orchestrat" not in service.DEVELOPER_WORKER_MISSION.lower()
    assert DevelopmentAssignmentInput(objective="Bounded work.").permitted_tools == []
