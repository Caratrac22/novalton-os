import copy
import json

import pytest
from pydantic import ValidationError

from novalton_api.modules.qa_worker.contracts import (
    MAX_DEFECTS,
    QAHumanReviewSummary,
    QAValidationInput,
    QAWorkerResult,
    human_review_summary,
)


def _result(*, verdict: str = "PASS") -> dict[str, object]:
    return {
        "status": "COMPLETED",
        "summary": "Bounded QA assessment.",
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
        "validation_summary": "The supplied metadata satisfies the criteria.",
        "verdict": verdict,
        "acceptance_results": [
            {
                "criterion_id": "criterion_two",
                "status": "PASS",
                "rationale": "The evidence supports the criterion.",
                "evidence_references": ["evidence:two"],
            },
            {
                "criterion_id": "criterion_one",
                "status": "PASS",
                "rationale": "The result metadata supports the criterion.",
                "evidence_references": ["evidence:one"],
            },
        ],
        "defects": [],
        "test_recommendations": ["Run the focused test suite later."],
        "regression_risks": [],
        "security_review_recommendations": [],
        "manual_review_recommendations": [],
        "blockers": [],
    }


def _validate(value: dict[str, object]) -> QAWorkerResult:
    return QAWorkerResult.model_validate_json(json.dumps(value))


def test_qa_result_is_strict_bounded_and_deterministic() -> None:
    value = _result(verdict="FAIL")
    value["acceptance_results"][0]["status"] = "FAIL"  # type: ignore[index]
    value["defects"] = [
        {
            "defect_key": "defect_two",
            "title": "Second defect",
            "severity": "LOW",
            "component_path": "apps/api/src/second.py",
            "description": "A bounded defect description.",
            "affected_criteria": ["criterion_two"],
            "remediation_summary": "Correct the described behavior.",
        },
        {
            "defect_key": "defect_one",
            "title": "First defect",
            "severity": "HIGH",
            "component_path": "apps/api/src/first.py",
            "description": "Another bounded defect description.",
            "affected_criteria": ["criterion_one"],
            "remediation_summary": "Correct the affected contract.",
        },
    ]
    result = _validate(value)
    assert [item.criterion_id for item in result.acceptance_results] == [
        "criterion_one",
        "criterion_two",
    ]
    assert [item.defect_key for item in result.defects] == ["defect_one", "defect_two"]


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../secret", "apps/../secret", "C:/secret", "https://bad.test/x"]
)
def test_qa_result_rejects_unsafe_paths(path: str) -> None:
    value = _result(verdict="FAIL")
    value["acceptance_results"][0]["status"] = "FAIL"  # type: ignore[index]
    value["defects"] = [
        {
            "defect_key": "defect_one",
            "title": "Defect",
            "severity": "HIGH",
            "component_path": path,
            "description": "Bounded description.",
            "affected_criteria": ["criterion_two"],
            "remediation_summary": "Correct the behavior.",
        }
    ]
    with pytest.raises(ValidationError):
        _validate(value)


def test_qa_result_rejects_duplicates_bounds_commands_and_extra_fields() -> None:
    duplicate = _result()
    duplicate["acceptance_results"] = [
        duplicate["acceptance_results"][0],  # type: ignore[index]
        duplicate["acceptance_results"][0],  # type: ignore[index]
    ]
    with pytest.raises(ValidationError, match="duplicate acceptance result"):
        _validate(duplicate)

    too_many = _result(verdict="FAIL")
    too_many["acceptance_results"][0]["status"] = "FAIL"  # type: ignore[index]
    too_many["defects"] = [
        {
            "defect_key": f"defect_{index}",
            "title": "Defect",
            "severity": "LOW",
            "description": "Bounded description.",
            "remediation_summary": "Correct the behavior.",
        }
        for index in range(MAX_DEFECTS + 1)
    ]
    with pytest.raises(ValidationError):
        _validate(too_many)

    unsafe = _result()
    unsafe["test_recommendations"] = ["sudo pytest"]
    with pytest.raises(ValidationError, match="executable"):
        _validate(unsafe)

    extra = _result()
    extra["shell_command"] = "pytest"
    with pytest.raises(ValidationError, match="Extra inputs"):
        _validate(extra)


def test_qa_verdict_consistency_and_challenge() -> None:
    failed_pass = _result()
    failed_pass["acceptance_results"][0]["status"] = "FAIL"  # type: ignore[index]
    with pytest.raises(ValidationError, match="PASS verdict"):
        _validate(failed_pass)

    inconclusive = _result(verdict="INCONCLUSIVE")
    inconclusive["status"] = "NEEDS_INPUT"
    inconclusive["acceptance_results"][0]["status"] = "NOT_VERIFIED"  # type: ignore[index]
    inconclusive["challenge"] = {
        "level": "HUMAN_REVIEW_RECOMMENDED",
        "reason": "Evidence is incomplete.",
        "evidence_source_references": ["evidence:two"],
        "suggested_action": "Request bounded evidence.",
    }
    result = _validate(inconclusive)
    assert result.verdict.value == "INCONCLUSIVE"
    assert result.status.value == "NEEDS_INPUT"


def test_qa_input_forbids_tools_overrides_and_duplicate_criteria() -> None:
    base = {
        "objective": "Validate one bounded implementation result.",
        "acceptance_criteria": [
            {"criterion_id": "criterion_one", "description": "Behavior is correct."}
        ],
    }
    assert QAValidationInput.model_validate(base).permitted_tools == []
    for change in (
        {"permitted_tools": ["shell"]},
        {"expected_output_type": "development.implementation_result"},
        {"model_requirements": {"tool_calling_required": True}},
        {"provider_url": "https://unsafe.example"},
    ):
        value = copy.deepcopy(base)
        value.update(change)
        with pytest.raises(ValidationError):
            QAValidationInput.model_validate(value)

    duplicate = copy.deepcopy(base)
    duplicate["acceptance_criteria"] *= 2
    with pytest.raises(ValidationError, match="duplicate validation criterion"):
        QAValidationInput.model_validate(duplicate)


def test_pass_with_warnings_builds_only_bounded_allow_listed_human_review_data() -> None:
    value = _result(verdict="PASS_WITH_WARNINGS")
    value["summary"] = "RAW_PROVIDER_OUTPUT_MUST_NOT_PERSIST"
    value["findings"] = [
        {
            "category": "provider_metadata",
            "title": "Prompt detail",
            "detail": "PROMPT_CONTENT_MUST_NOT_PERSIST",
        }
    ]
    value["challenge"] = {
        "level": "HUMAN_REVIEW_RECOMMENDED",
        "reason": "One criterion needs a human evidence judgment.",
        "evidence_source_references": ["evidence:one"],
        "suggested_action": "Review the bounded evidence state.",
    }
    value["acceptance_results"][0]["status"] = "NOT_VERIFIED"  # type: ignore[index]
    value["acceptance_results"][0]["rationale"] = "The persisted evidence is incomplete."  # type: ignore[index]
    value["regression_risks"] = ["A later change could invalidate the evidence binding."]
    value["test_recommendations"] = ["Repeat the bounded negative check."]
    value["security_review_recommendations"] = ["Confirm the approval fingerprint binding."]
    value["manual_review_recommendations"] = ["Inspect the safe mutation metadata."]

    summary = human_review_summary(_validate(value))
    payload = summary.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["verdict"] == "PASS_WITH_WARNINGS"
    assert payload["warnings"] == [
        {
            "category": "REGRESSION_RISK",
            "message": "A later change could invalidate the evidence binding.",
        }
    ]
    assert [item["category"] for item in payload["recommendations"]] == [
        "TEST",
        "SECURITY_REVIEW",
        "MANUAL_REVIEW",
    ]
    assert payload["acceptance_results"][1]["rationale"] == (
        "The persisted evidence is incomplete."
    )
    assert "RAW_PROVIDER_OUTPUT_MUST_NOT_PERSIST" not in serialized
    assert "PROMPT_CONTENT_MUST_NOT_PERSIST" not in serialized
    assert set(payload) == {
        "schema_version",
        "verdict",
        "challenge_level",
        "challenge_reason",
        "challenge_evidence_references",
        "suggested_action",
        "validation_summary",
        "warnings",
        "recommendations",
        "acceptance_results",
        "concerns",
    }


def test_human_review_summary_bounds_and_secret_sanitization_fail_closed() -> None:
    value = _result(verdict="PASS_WITH_WARNINGS")
    value["challenge"] = {
        "level": "HUMAN_REVIEW_RECOMMENDED",
        "reason": "Review bounded evidence.",
        "evidence_source_references": [],
        "suggested_action": None,
    }
    value["test_recommendations"] = ["Authorization: Bearer hidden-secret-value"]
    with pytest.raises(ValidationError, match="credential"):
        _validate(value)

    valid = human_review_summary(
        _validate(
            _result(verdict="PASS_WITH_WARNINGS")
            | {
                "challenge": {
                    "level": "HUMAN_REVIEW_RECOMMENDED",
                    "reason": "Review bounded evidence.",
                    "evidence_source_references": [],
                    "suggested_action": None,
                }
            }
        )
    ).model_dump(mode="json")
    valid["warnings"] = [{"category": "BLOCKER", "message": "x" * 501}]
    with pytest.raises(ValidationError):
        QAHumanReviewSummary.model_validate(valid, strict=True)
