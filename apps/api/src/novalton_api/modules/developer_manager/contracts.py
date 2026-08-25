"""Strict proposal-only contracts for the Developer Manager Agent."""

import heapq
import re
from enum import StrEnum
from typing import Annotated, ClassVar, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from novalton_api.modules.agents.contract_execution import SemanticConstraint
from novalton_api.modules.agents.contracts import (
    AgentInput,
    AgentResult,
    ContractModel,
    Identifier,
    RequestedAction,
    ShortText,
    _identifier,
    _safe_text,
    _unique_sorted,
)
from novalton_api.modules.policy.schemas import RiskLevel

DEVELOPMENT_PLAN_OUTPUT = "development.plan_proposal"
MAX_PROPOSED_TASKS = 16
_TASK_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TaskKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=_TASK_KEY.pattern,
    ),
]


class ReviewRecommendation(StrEnum):
    NOT_NEEDED = "NOT_NEEDED"
    RECOMMENDED = "RECOMMENDED"
    REQUIRED = "REQUIRED"


class DevelopmentPlanningInput(AgentInput):
    """A bounded AgentInput with no tool or model-selection authority."""

    expected_output_type: Identifier = DEVELOPMENT_PLAN_OUTPUT
    permitted_tools: list[Identifier] = Field(default_factory=list, max_length=0)

    @model_validator(mode="after")
    def validate_manager_input(self) -> Self:
        if self.expected_output_type != DEVELOPMENT_PLAN_OUTPUT:
            raise ValueError("expected_output_type must request a development plan proposal")
        if self.model_requirements is not None and self.model_requirements.tool_calling_required:
            raise ValueError("Developer Manager planning cannot require tool calling")
        return self


class ProposedWorkerTask(ContractModel):
    task_key: TaskKey
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1500)
    required_capabilities: list[Identifier] = Field(min_length=1, max_length=12)
    depends_on: list[TaskKey] = Field(default_factory=list, max_length=15)
    expected_output: Identifier
    acceptance_criteria: list[ShortText] = Field(min_length=1, max_length=12)
    risk_level: RiskLevel

    @field_validator("task_key")
    @classmethod
    def normalize_task_key(cls, value: str) -> str:
        value = value.strip().lower()
        if _TASK_KEY.fullmatch(value) is None:
            raise ValueError("task_key must be a normalized stable identifier")
        return value

    @field_validator("title", "objective")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("required_capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_identifier(value) for value in values])

    @field_validator("depends_on")
    @classmethod
    def normalize_dependencies(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate task dependency")
        if any(_TASK_KEY.fullmatch(value) is None for value in normalized):
            raise ValueError("dependency must be a normalized task key")
        return sorted(normalized)

    @field_validator("expected_output")
    @classmethod
    def normalize_expected_output(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_acceptance_criteria(cls, values: list[str]) -> list[str]:
        normalized = [_safe_text(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate acceptance criterion")
        return sorted(normalized)


class DevelopmentPlanProposal(ContractModel):
    objective_interpretation: str = Field(min_length=1, max_length=2000)
    architecture_workstreams: list[ShortText] = Field(min_length=1, max_length=12)
    proposed_tasks: list[ProposedWorkerTask] = Field(min_length=1, max_length=MAX_PROPOSED_TASKS)
    qa_review: ReviewRecommendation
    security_review: ReviewRecommendation
    manual_review: ReviewRecommendation

    @field_validator("objective_interpretation")
    @classmethod
    def validate_interpretation(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("architecture_workstreams")
    @classmethod
    def normalize_workstreams(cls, values: list[str]) -> list[str]:
        normalized = [_safe_text(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate architecture workstream")
        return sorted(normalized)

    @model_validator(mode="after")
    def validate_dependency_graph(self) -> Self:
        by_key = {task.task_key: task for task in self.proposed_tasks}
        if len(by_key) != len(self.proposed_tasks):
            raise ValueError("proposed task keys must be unique")
        indegree = {key: 0 for key in by_key}
        dependents: dict[str, list[str]] = {key: [] for key in by_key}
        for task in self.proposed_tasks:
            for dependency in task.depends_on:
                if dependency == task.task_key:
                    raise ValueError("proposed task cannot depend on itself")
                if dependency not in by_key:
                    raise ValueError("dependency must reference an existing proposed task")
                indegree[task.task_key] += 1
                dependents[dependency].append(task.task_key)
        ready = [key for key, count in indegree.items() if count == 0]
        heapq.heapify(ready)
        ordered_keys: list[str] = []
        while ready:
            key = heapq.heappop(ready)
            ordered_keys.append(key)
            for dependent in sorted(dependents[key]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(ready, dependent)
        if len(ordered_keys) != len(by_key):
            raise ValueError("proposed task dependencies must be acyclic")
        return self.model_copy(update={"proposed_tasks": [by_key[key] for key in ordered_keys]})


class DeveloperManagerResult(AgentResult):
    """AgentResult enriched only with the bounded development proposal."""

    semantic_constraints: ClassVar[tuple[SemanticConstraint, ...]] = (
        SemanticConstraint(
            code="proposed_task_keys_unique",
            path="development_plan.proposed_tasks[*].task_key",
            instruction="Each proposed task_key must be unique within proposed_tasks.",
        ),
        SemanticConstraint(
            code="dependency_existing_task",
            path="development_plan.proposed_tasks[*].depends_on",
            instruction="Every dependency must reference a task_key present in proposed_tasks.",
        ),
        SemanticConstraint(
            code="dependency_acyclic",
            path="development_plan.proposed_tasks",
            instruction=(
                "The dependency graph must be acyclic and a task must not depend on itself."
            ),
        ),
    )
    development_plan: DevelopmentPlanProposal
    requested_actions: list[RequestedAction] = Field(default_factory=list, max_length=0)
