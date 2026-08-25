"""Focused tests for contextual result-shape contract compilation and validation."""

from novalton_api.modules.agents.contract_execution import (
    ResultShapeConstraint,
    compile_contract,
    validate_result_shape,
)
from novalton_api.modules.agents.contracts import (
    AgentResultStatus,
    Challenge,
    ChallengeLevel,
)
from novalton_api.modules.developer_manager.contracts import (
    DeveloperManagerResult,
    DevelopmentPlanProposal,
    ProposedWorkerTask,
    ReviewRecommendation,
)
from novalton_api.modules.policy.schemas import RiskLevel


def _task(task_key: str, *, depends_on: list[str] | None = None) -> ProposedWorkerTask:
    return ProposedWorkerTask(
        task_key=task_key,
        title=f"Implement {task_key}",
        objective=f"Complete {task_key}.",
        required_capabilities=["coding"],
        depends_on=depends_on or [],
        expected_output="code.patch",
        acceptance_criteria=["The bounded change is complete."],
        risk_level=RiskLevel.LOW,
    )


def _manager_result(tasks: list[ProposedWorkerTask]) -> DeveloperManagerResult:
    return DeveloperManagerResult(
        status=AgentResultStatus.COMPLETED,
        summary="Bounded development plan.",
        findings=[],
        artifacts=[],
        sources=[],
        assumptions=[],
        risks=[],
        uncertainties=[],
        blocking_issues=[],
        challenge=Challenge(level=ChallengeLevel.NONE),
        recommended_next_steps=[],
        requested_actions=[],
        development_plan=DevelopmentPlanProposal(
            objective_interpretation="Complete the bounded implementation.",
            architecture_workstreams=["implementation"],
            proposed_tasks=tasks,
            qa_review=ReviewRecommendation.RECOMMENDED,
            security_review=ReviewRecommendation.NOT_NEEDED,
            manual_review=ReviewRecommendation.NOT_NEEDED,
        ),
    )


def _fixed_constraints() -> tuple[ResultShapeConstraint, ...]:
    return (
        ResultShapeConstraint.exact_items(
            code="fixed_manager_task_count",
            path="development_plan.proposed_tasks",
            count=1,
        ),
        ResultShapeConstraint.empty(
            code="fixed_manager_task_dependencies_empty",
            path="development_plan.proposed_tasks[0].depends_on",
        ),
    )


def test_unrestricted_manager_contract_allows_multiple_tasks_and_dependencies() -> None:
    result = _manager_result([_task("first"), _task("second", depends_on=["first"])])

    assert len(result.development_plan.proposed_tasks) == 2
    assert result.development_plan.proposed_tasks[1].depends_on == ["first"]
    assert not validate_result_shape(result, ())


def test_fixed_constraints_compile_into_effective_schema_without_mutating_base() -> None:
    base = compile_contract(DeveloperManagerResult)
    effective = compile_contract(
        DeveloperManagerResult,
        result_shape_constraints=_fixed_constraints(),
    )

    plan_schema = effective.json_schema["$defs"]["DevelopmentPlanProposal"]
    task_schema = effective.json_schema["$defs"]["ProposedWorkerTask"]
    assert plan_schema["properties"]["proposed_tasks"]["minItems"] == 1
    assert plan_schema["properties"]["proposed_tasks"]["maxItems"] == 1
    assert task_schema["properties"]["depends_on"]["maxItems"] == 0
    assert (
        base.json_schema["$defs"]["DevelopmentPlanProposal"]["properties"]["proposed_tasks"][
            "maxItems"
        ]
        == 16
    )


def test_contextual_constraints_are_fingerprinted_deterministically() -> None:
    constraints = _fixed_constraints()
    first = compile_contract(DeveloperManagerResult, result_shape_constraints=constraints)
    second = compile_contract(DeveloperManagerResult, result_shape_constraints=constraints)
    unrestricted = compile_contract(DeveloperManagerResult)

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != unrestricted.fingerprint


def test_contextual_validation_reports_only_safe_codes_and_paths() -> None:
    two_tasks = _manager_result([_task("first"), _task("second")])
    dependent_task = _manager_result([_task("first"), _task("second", depends_on=["first"])])

    count_failures = validate_result_shape(two_tasks, _fixed_constraints())
    dependency_constraint = ResultShapeConstraint.empty(
        code="all_manager_task_dependencies_empty",
        path="development_plan.proposed_tasks[*].depends_on",
    )
    dependency_failures = validate_result_shape(dependent_task, (dependency_constraint,))

    assert [(failure.code, failure.path) for failure in count_failures] == [
        ("fixed_manager_task_count", "development_plan.proposed_tasks")
    ]
    assert [(failure.code, failure.path) for failure in dependency_failures] == [
        (
            "all_manager_task_dependencies_empty",
            "development_plan.proposed_tasks[*].depends_on",
        )
    ]
    assert "first" not in repr(dependency_failures)


def test_compliant_contextual_result_passes_local_validation() -> None:
    result = _manager_result([_task("only")])

    assert validate_result_shape(result, _fixed_constraints()) == ()


def test_bounded_semantic_constraint_validates_locally_without_schema_hacks() -> None:
    result = _manager_result([_task("only")])
    constraint = ResultShapeConstraint.semantic(
        code="manager_qa_review_required",
        path="development_plan.qa_review",
        instruction="The manager must recommend QA review.",
        validator=lambda value: value == "RECOMMENDED",
    )

    assert validate_result_shape(result, (constraint,)) == ()
