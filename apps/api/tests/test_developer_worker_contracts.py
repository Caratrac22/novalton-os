import copy
import json

import pytest
from pydantic import ValidationError

from novalton_api.modules.developer_worker.contracts import (
    MAX_PROPOSED_CHANGES,
    DeveloperWorkerResult,
    DevelopmentAssignmentInput,
)


def _result() -> dict[str, object]:
    return {
        "status": "COMPLETED",
        "summary": "A bounded implementation proposal.",
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
        "task_interpretation": "Change the scoped API contract.",
        "implementation_summary": "Propose the contract and focused tests.",
        "changes": [
            {
                "path": "apps/api/tests/test_feature.py",
                "kind": "TEST",
                "rationale": "Cover behavior.",
                "expected_effect": "Prevent regressions.",
                "acceptance_criteria": ["tests_pass"],
            },
            {
                "path": "apps/api/src/feature.py",
                "kind": "MODIFY",
                "rationale": "Implement behavior.",
                "expected_effect": "Satisfy the contract.",
                "acceptance_criteria": ["contract_valid"],
            },
        ],
        "acceptance_checks": [
            {"criterion_id": "tests_pass", "status": "NOT_VERIFIED", "detail": "Run tests."},
            {"criterion_id": "contract_valid", "status": "SATISFIED", "detail": "Validated."},
        ],
        "test_recommendations": ["Run focused tests.", "Run all backend tests."],
        "blockers": [],
    }


def test_worker_result_normalizes_metadata_deterministically() -> None:
    result = DeveloperWorkerResult.model_validate_json(json.dumps(_result()))
    assert [change.path for change in result.changes] == [
        "apps/api/src/feature.py",
        "apps/api/tests/test_feature.py",
    ]
    assert [check.criterion_id for check in result.acceptance_checks] == [
        "contract_valid",
        "tests_pass",
    ]
    assert result.test_recommendations == ["Run all backend tests.", "Run focused tests."]


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../secret", "apps/../secret", "C:/secret", "https://example.test/x"],
)
def test_worker_result_rejects_absolute_traversal_and_url_paths(path: str) -> None:
    value = _result()
    value["changes"][0]["path"] = path  # type: ignore[index]
    with pytest.raises(ValidationError, match="normalized relative path"):
        DeveloperWorkerResult.model_validate_json(json.dumps(value))


def test_worker_result_rejects_duplicates_bounds_and_executable_fields() -> None:
    duplicate = _result()
    duplicate["changes"] = [duplicate["changes"][0], duplicate["changes"][0]]  # type: ignore[index]
    with pytest.raises(ValidationError, match="duplicate proposed change"):
        DeveloperWorkerResult.model_validate_json(json.dumps(duplicate))

    too_many = _result()
    too_many["changes"] = [
        {
            "path": f"src/file_{index}.py",
            "kind": "MODIFY",
            "rationale": "Bounded change.",
            "expected_effect": "Bounded effect.",
        }
        for index in range(MAX_PROPOSED_CHANGES + 1)
    ]
    with pytest.raises(ValidationError):
        DeveloperWorkerResult.model_validate_json(json.dumps(too_many))

    unsafe = _result()
    unsafe["changes"][0]["shell_command"] = "rm -rf repo"  # type: ignore[index]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DeveloperWorkerResult.model_validate_json(json.dumps(unsafe))


def test_worker_input_allows_only_trusted_tools_and_forbids_provider_overrides() -> None:
    base = {"objective": "Implement one bounded change."}
    assert DevelopmentAssignmentInput.model_validate(base).permitted_tools == []
    assert DevelopmentAssignmentInput.model_validate(
        base | {"permitted_tools": ["workspace.read_file"]}
    ).permitted_tools == ["workspace.read_file"]
    for change in (
        {"permitted_tools": ["shell"]},
        {"expected_output_type": "qa.result"},
        {"model_requirements": {"tool_calling_required": True}},
        {"provider_url": "https://unsafe.example"},
    ):
        value = copy.deepcopy(base)
        value.update(change)
        with pytest.raises(ValidationError):
            DevelopmentAssignmentInput.model_validate(value)
