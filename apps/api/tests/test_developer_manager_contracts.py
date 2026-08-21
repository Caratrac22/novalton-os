import copy
import json

import pytest
from pydantic import ValidationError

from novalton_api.modules.developer_manager.contracts import (
    MAX_PROPOSED_TASKS,
    DevelopmentPlanningInput,
    DevelopmentPlanProposal,
)


def _task(key: str, *, depends_on: list[str] | None = None) -> dict[str, object]:
    return {
        "task_key": key,
        "title": f"Task {key}",
        "objective": f"Produce the bounded {key} result.",
        "required_capabilities": ["testing", "software_architecture"],
        "depends_on": depends_on or [],
        "expected_output": f"{key}.result",
        "acceptance_criteria": ["Output is reviewed", "Contract is satisfied"],
        "risk_level": "LOW",
    }


def _proposal(tasks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "objective_interpretation": "Implement only the bounded requested change.",
        "architecture_workstreams": ["Tests", "Backend"],
        "proposed_tasks": tasks,
        "qa_review": "RECOMMENDED",
        "security_review": "NOT_NEEDED",
        "manual_review": "REQUIRED",
    }


def test_proposal_normalizes_deterministically_in_stable_topological_order() -> None:
    proposal = DevelopmentPlanProposal.model_validate_json(
        json.dumps(
            _proposal(
                [
                    _task("qa", depends_on=["frontend", "backend"]),
                    _task("frontend", depends_on=["architecture"]),
                    _task("architecture"),
                    _task("backend", depends_on=["architecture"]),
                ]
            )
        )
    )

    assert [task.task_key for task in proposal.proposed_tasks] == [
        "architecture",
        "backend",
        "frontend",
        "qa",
    ]
    assert proposal.proposed_tasks[-1].depends_on == ["backend", "frontend"]
    assert proposal.architecture_workstreams == ["Backend", "Tests"]
    assert proposal.proposed_tasks[0].required_capabilities == [
        "software_architecture",
        "testing",
    ]


@pytest.mark.parametrize(
    ("tasks", "message"),
    [
        ([_task("same"), _task("same")], "unique"),
        ([_task("only", depends_on=["missing"])], "existing proposed task"),
        ([_task("only", depends_on=["only"])], "itself"),
        ([_task("a"), _task("b", depends_on=["a", "a"])], "duplicate task dependency"),
        ([_task("a", depends_on=["b"]), _task("b", depends_on=["a"])], "acyclic"),
    ],
)
def test_proposal_rejects_invalid_dependency_graphs(
    tasks: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        DevelopmentPlanProposal.model_validate_json(json.dumps(_proposal(tasks)))


def test_proposal_bounds_task_count_and_forbids_arbitrary_fields() -> None:
    too_many = [_task(f"task_{index}") for index in range(MAX_PROPOSED_TASKS + 1)]
    with pytest.raises(ValidationError):
        DevelopmentPlanProposal.model_validate_json(json.dumps(_proposal(too_many)))

    value = _proposal([_task("one")])
    value["provider_override"] = "unsafe"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DevelopmentPlanProposal.model_validate_json(json.dumps(value))


def test_planning_input_forbids_tools_and_output_or_model_overrides() -> None:
    base = {
        "objective": "Decompose this bounded development objective.",
        "expected_output_type": "development.plan_proposal",
    }
    assert DevelopmentPlanningInput.model_validate(base).permitted_tools == []

    for change in (
        {"permitted_tools": ["shell"]},
        {"expected_output_type": "workflow.plan"},
        {"model_requirements": {"tool_calling_required": True}},
        {"provider_url": "https://unsafe.example"},
    ):
        value = copy.deepcopy(base)
        value.update(change)
        with pytest.raises(ValidationError):
            DevelopmentPlanningInput.model_validate(value)
