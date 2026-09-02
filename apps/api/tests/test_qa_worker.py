import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from novalton_api.core.config import Settings  # noqa: F401
from novalton_api.core.database import Database  # noqa: F401
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents.schemas import AgentExecutionResponse, AgentRunStatus
from novalton_api.modules.qa_worker import service
from novalton_api.modules.qa_worker.contracts import QAValidationInput, QAWorkerResult
from novalton_api.modules.qa_worker.schemas import QAWorkerValidationRequest


def _result() -> QAWorkerResult:
    return QAWorkerResult.model_validate_json(
        json.dumps(
            {
                "status": "COMPLETED",
                "summary": "Bounded QA result.",
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
                "validation_summary": "Evidence supports the criterion.",
                "verdict": "PASS",
                "acceptance_results": [
                    {
                        "criterion_id": "criterion_one",
                        "status": "PASS",
                        "rationale": "Metadata supports the criterion.",
                    }
                ],
                "defects": [],
                "test_recommendations": ["Run focused tests later."],
                "regression_risks": [],
                "security_review_recommendations": [],
                "manual_review_recommendations": [],
                "blockers": [],
            }
        )
    )


@pytest.mark.asyncio
async def test_qa_worker_uses_i022_execution_exactly_once(monkeypatch) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    definition_id = uuid4()
    run_id = uuid4()
    definition = SimpleNamespace(id=definition_id, version=1, status="ENABLED")
    calls: list[dict[str, object]] = []

    async def latest_definition(session, **kwargs):
        assert kwargs == {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "slug": service.QA_WORKER_SLUG,
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
            result=_result(),
        )

    monkeypatch.setattr(service.repository, "latest_definition", latest_definition)
    monkeypatch.setattr(service.execution, "execute", execute)
    data = QAWorkerValidationRequest(
        objective="Validate bounded metadata.",
        acceptance_criteria=[
            {"criterion_id": "criterion_one", "description": "Behavior is correct."}
        ],
    )
    response = await service.validate(
        object(),
        registry=object(),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )

    assert len(calls) == 1
    assert calls[0]["definition_id"] == definition_id
    assert calls[0]["data"] is data
    assert calls[0]["result_contract"] is QAWorkerResult
    assert response.result is not None
    assert response.result.verdict.value == "PASS"
    assert response.result.requested_actions == []


@pytest.mark.asyncio
async def test_qa_worker_resolves_latest_same_scope_and_rejects_unavailable(monkeypatch) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    captured: list[dict[str, object]] = []

    async def missing(session, **kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr(service.repository, "latest_definition", missing)
    with pytest.raises(ApplicationError) as missing_error:
        await service.resolve_definition(object(), tenant_id=tenant_id, workspace_id=workspace_id)
    assert missing_error.value.code == "qa_worker_unavailable"
    assert captured == [
        {
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "slug": service.QA_WORKER_SLUG,
            "exclude_archived": True,
        }
    ]

    async def disabled(session, **kwargs):
        return SimpleNamespace(status="DISABLED")

    monkeypatch.setattr(service.repository, "latest_definition", disabled)
    with pytest.raises(ApplicationError) as disabled_error:
        await service.resolve_definition(object(), tenant_id=tenant_id, workspace_id=workspace_id)
    assert disabled_error.value.code == "qa_worker_unavailable"


def test_qa_worker_is_normal_governed_agent_metadata() -> None:
    assert service.QA_WORKER_SLUG == "qa_worker"
    assert service.QA_WORKER_CATEGORY == "quality"
    assert sorted(service.QA_WORKER_CAPABILITIES) == service.QA_WORKER_CAPABILITIES
    assert "orchestrat" not in service.QA_WORKER_MISSION.lower()
    assert (
        QAValidationInput(
            objective="Bounded QA.",
            acceptance_criteria=[
                {"criterion_id": "criterion_one", "description": "Behavior is correct."}
            ],
        ).permitted_tools
        == []
    )
