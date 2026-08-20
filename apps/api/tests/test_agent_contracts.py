"""Security and boundary tests for pure structured agent contracts."""

import json

import pytest
from pydantic import ValidationError

from novalton_api.core.database import Base
from novalton_api.modules.agents.contracts import (
    AgentInput,
    AgentResult,
    AgentResultStatus,
    ArtifactReference,
    Assumption,
    BlockingIssue,
    Challenge,
    ChallengeLevel,
    Finding,
    FindingSeverity,
    RecommendedNextStep,
    RequestedAction,
    Risk,
    SourceReference,
    Uncertainty,
)
from novalton_api.modules.agents.schemas import AgentRunStatus
from novalton_api.modules.policy.schemas import RiskLevel


def _input(**changes: object) -> AgentInput:
    values: dict[str, object] = {
        "objective": "Review the referenced implementation.",
        "constraints": ["Do not modify files."],
        "project_id": "prj_123",
        "task_id": "tsk_456",
        "context_references": [{"reference_id": "ctx_1", "label": "Repository snapshot"}],
        "source_references": ["src_2", "src_1"],
        "prior_result_references": ["result_1"],
        "expected_output_type": "code_review.report",
        "permitted_tools": ["repository.read"],
        "model_requirements": {
            "required_capabilities": ["structured_output", "reasoning"],
            "minimum_context_tokens": 1000,
        },
    }
    values.update(changes)
    return AgentInput(**values)


def _result(**changes: object) -> AgentResult:
    values: dict[str, object] = {
        "status": AgentResultStatus.PARTIAL,
        "summary": "The review found one issue and one unresolved assumption.",
        "findings": [
            Finding(
                category="security",
                title="Missing boundary check",
                detail="The referenced validation path lacks a scope check.",
                severity=FindingSeverity.HIGH,
                source_references=["src_1"],
            )
        ],
        "artifacts": [
            ArtifactReference(
                artifact_id="artifact_1",
                artifact_type="report",
                label="Review report",
                path="reports/review.md",
                content_type="text/markdown",
            )
        ],
        "sources": [
            SourceReference(
                source_id="src_1",
                label="Agent service",
                source_type="repository_file",
                provenance_uri="https://example.invalid/repository/service.py",
            )
        ],
        "assumptions": [Assumption(statement="The snapshot is current.")],
        "risks": [Risk(statement="A cross-scope read may occur.", severity=RiskLevel.HIGH)],
        "uncertainties": [Uncertainty(statement="Deployment configuration was not supplied.")],
        "blocking_issues": [BlockingIssue(statement="Required fixture is unavailable.")],
        "challenge": Challenge(
            level=ChallengeLevel.HUMAN_REVIEW_RECOMMENDED,
            reason="The affected boundary is security-sensitive.",
            evidence_source_references=["src_1"],
            suggested_action="Ask a maintainer to review the proposed change.",
        ),
        "recommended_next_steps": [
            RecommendedNextStep(recommendation="Add a deterministic scope test.")
        ],
        "requested_actions": [
            RequestedAction(
                action_type="repository.write",
                target_reference="repo:novalton-os",
                reason="Apply the reviewed validation fix.",
                risk_hint=RiskLevel.MEDIUM,
            )
        ],
    }
    values.update(changes)
    return AgentResult(**values)


def test_agent_input_is_strict_bounded_and_deterministically_normalized() -> None:
    value = _input(
        constraints=["No writes.", "No writes.", "Keep scope narrow."],
        source_references=["src_b", "src_a", "src_b"],
        permitted_tools=["repository.read", "repository.read"],
    )
    assert value.constraints == ["Keep scope narrow.", "No writes."]
    assert value.source_references == ["src_a", "src_b"]
    assert value.permitted_tools == ["repository.read"]

    rejected = (
        {"objective": "x" * 4001},
        {"constraints": ["x"] * 33},
        {"source_references": ["src"] * 33},
        {"prior_result_references": [f"result_{index}" for index in range(17)]},
        {"expected_output_type": "invalid output"},
        {"permitted_tools": [f"tool_{index}" for index in range(33)]},
        {"task_id": "tsk_1", "project_id": None},
        {"provider_request": {"model": "provider/model"}},
        {"authorization": "Bearer secret"},
        {"policy_dsl": "allow(*)"},
        {"tool_arguments": {"path": "/tmp"}},
        {"model_id": "provider/model"},
        {"network_request": {"url": "https://example.invalid"}},
        {"source_references": ["https://example.invalid/source"]},
    )
    for change in rejected:
        with pytest.raises(ValidationError):
            _input(**change)


def test_agent_input_rejects_secret_material_and_nested_extras() -> None:
    with pytest.raises(ValidationError):
        _input(objective="Use Authorization: Bearer abcdefghijklmnop")
    with pytest.raises(ValidationError):
        _input(context_references=[{"reference_id": "ctx_1", "body": "raw source"}])
    with pytest.raises(ValidationError):
        _input(model_requirements={"provider": "example", "model": "override"})


def test_agent_result_requires_every_distinct_bounded_collection() -> None:
    value = _result()
    assert value.assumptions[0].statement != value.risks[0].statement
    assert value.uncertainties[0].statement != value.blocking_issues[0].statement
    assert set(AgentResultStatus) == {
        AgentResultStatus.COMPLETED,
        AgentResultStatus.PARTIAL,
        AgentResultStatus.BLOCKED,
        AgentResultStatus.NEEDS_INPUT,
        AgentResultStatus.FAILED,
        AgentResultStatus.CANCELLED,
    }
    assert set(AgentResultStatus) != set(AgentRunStatus)

    payload = value.model_dump(mode="json")
    for required in (
        "findings",
        "artifacts",
        "sources",
        "assumptions",
        "risks",
        "uncertainties",
        "blocking_issues",
        "challenge",
        "recommended_next_steps",
        "requested_actions",
    ):
        missing = dict(payload)
        missing.pop(required)
        with pytest.raises(ValidationError):
            AgentResult.model_validate(missing)


def test_nested_result_models_are_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        _result(findings=[{"category": "security", "title": "x", "detail": "y", "score": 9}])
    with pytest.raises(ValidationError):
        _result(findings=[{"category": "security", "title": "x" * 301, "detail": "y"}])
    with pytest.raises(ValidationError):
        _result(assumptions=[{"statement": "x" * 1001}])
    with pytest.raises(ValidationError):
        _result(risks=[{"statement": "risk", "severity": "EXTREME"}])
    with pytest.raises(ValidationError):
        _result(status="SUCCEEDED")


@pytest.mark.parametrize(
    ("field", "count"),
    [
        ("findings", 65),
        ("artifacts", 33),
        ("sources", 65),
        ("assumptions", 33),
        ("risks", 33),
        ("uncertainties", 33),
        ("blocking_issues", 33),
        ("recommended_next_steps", 33),
        ("requested_actions", 33),
    ],
)
def test_every_result_collection_is_bounded(field: str, count: int) -> None:
    value = _result()
    with pytest.raises(ValidationError):
        _result(**{field: [getattr(value, field)[0]] * count})


def test_nested_reference_collections_and_model_hints_are_bounded() -> None:
    with pytest.raises(ValidationError):
        _input(context_references=[{"reference_id": f"ctx_{index}"} for index in range(33)])
    with pytest.raises(ValidationError):
        _input(
            model_requirements={
                "required_capabilities": [f"capability_{index}" for index in range(17)]
            }
        )
    with pytest.raises(ValidationError):
        Finding(
            category="security",
            title="Finding",
            detail="Detail",
            source_references=[f"src_{index}" for index in range(17)],
        )
    with pytest.raises(ValidationError):
        Assumption(
            statement="Assumption",
            source_references=[f"src_{index}" for index in range(9)],
        )
    with pytest.raises(ValidationError):
        Challenge(
            level=ChallengeLevel.WARNING,
            reason="Review needed.",
            evidence_source_references=[f"src_{index}" for index in range(17)],
        )


@pytest.mark.parametrize(
    "uri",
    [
        "file:///etc/passwd",
        "https://user:password@example.invalid/source",
        "https://example.invalid/source?X-Amz-Signature=secret",
        "https://example.invalid/source#token",
        "not-a-uri",
    ],
)
def test_sources_are_safe_metadata_only(uri: str) -> None:
    with pytest.raises(ValidationError):
        SourceReference(source_id="src_1", label="Source", provenance_uri=uri)
    with pytest.raises(ValidationError):
        SourceReference(source_id="src_1", label="Source", raw_body="contents")
    with pytest.raises(ValidationError):
        SourceReference(source_id="src_1", label="api_key=secret")


def test_challenge_levels_and_consistency() -> None:
    assert Challenge(level=ChallengeLevel.NONE).reason is None
    for level in ChallengeLevel:
        if level != ChallengeLevel.NONE:
            assert Challenge(level=level, reason="Review this condition.").level == level
            with pytest.raises(ValidationError):
                Challenge(level=level)
    with pytest.raises(ValidationError):
        Challenge(level=ChallengeLevel.NONE, reason="Contradictory warning")
    with pytest.raises(ValidationError):
        Challenge(level=ChallengeLevel.NONE, suggested_action="Block the run")
    with pytest.raises(ValidationError):
        Challenge(level=ChallengeLevel.NONE, evidence_source_references=["src_1"])


def test_requested_actions_are_non_executable_proposals_only() -> None:
    value = RequestedAction(
        action_type="repository.write",
        target_reference="repo:novalton-os",
        reason="Apply a reviewed patch.",
    )
    assert not hasattr(value, "approved")
    for field, payload in (
        ("approved", True),
        ("policy_effect", "ALLOW"),
        ("execute", True),
        ("function_call", {"name": "write", "arguments": {}}),
        ("payload", {"command": "rm -rf /"}),
        ("command", "rm -rf /"),
        ("tool_call", {"tool": "shell"}),
    ):
        values = value.model_dump(mode="python") | {field: payload}
        with pytest.raises(ValidationError):
            RequestedAction.model_validate(values)


def test_artifacts_reject_embedded_content_and_binary_fields() -> None:
    for field, payload in (
        ("body", "raw artifact"),
        ("content", "raw artifact"),
        ("base64", "SGVsbG8="),
        ("bytes", [1, 2, 3]),
    ):
        with pytest.raises(ValidationError):
            ArtifactReference(
                artifact_id="artifact_1",
                artifact_type="report",
                label="Report",
                **{field: payload},
            )
    with pytest.raises(ValidationError):
        ArtifactReference(
            artifact_id="artifact_1",
            artifact_type="image",
            label="Image",
            path="data:image/png;base64,SGVsbG8=",
        )
    with pytest.raises(ValidationError):
        ArtifactReference(
            artifact_id="artifact_1",
            artifact_type="binary",
            label="Embedded bytes",
            path="A" * 128,
        )


def test_serialization_round_trip_is_stable_and_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for target in (
        "novalton_api.modules.model_router.service.simulate",
        "novalton_api.infrastructure.providers.registry.ProviderRegistry.get",
    ):
        monkeypatch.setattr(
            target,
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("execution called")),
        )

    input_value = _input()
    result_value = _result()
    assert AgentInput.model_validate_json(input_value.model_dump_json()) == input_value
    assert AgentResult.model_validate_json(result_value.model_dump_json()) == result_value
    assert json.loads(result_value.model_dump_json())["status"] == "PARTIAL"
    agent_runs = Base.metadata.tables["agent_runs"]
    assert "input_json" not in agent_runs.c
    assert "result_json" not in agent_runs.c
    assert "model_runs" in Base.metadata.tables
