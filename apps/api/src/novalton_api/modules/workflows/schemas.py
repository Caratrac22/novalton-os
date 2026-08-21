"""Strict bounded workflow API and internal lifecycle contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ChangeReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
StepKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Capability = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

MAX_PLAN_STEPS = 100
MAX_PLAN_EDGES = 500


class WorkflowStepType(StrEnum):
    AGENT_TASK = "AGENT_TASK"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SYSTEM = "SYSTEM"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkflowRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStepRunStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStepCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    step_key: StepKey
    title: Title
    step_type: WorkflowStepType
    assigned_capability: Capability | None = None
    agent_definition_id: UUID | None = None
    risk_level: RiskLevel | None = None
    depends_on: Annotated[list[StepKey], Field(default_factory=list, max_length=MAX_PLAN_STEPS)]

    @field_validator("step_type", mode="before")
    @classmethod
    def parse_step_type(cls, value: object) -> object:
        return WorkflowStepType(value.upper()) if isinstance(value, str) else value

    @field_validator("risk_level", mode="before")
    @classmethod
    def parse_risk_level(cls, value: object) -> object:
        return RiskLevel(value.upper()) if isinstance(value, str) else value

    @field_validator("depends_on")
    @classmethod
    def unique_dependencies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate dependency")
        return value


class WorkflowPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: Title
    summary: Summary | None = None
    steps: Annotated[list[WorkflowStepCreate], Field(min_length=1, max_length=MAX_PLAN_STEPS)]

    @model_validator(mode="after")
    def graph_bounds(self) -> "WorkflowPlanCreate":
        keys = [step.step_key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("step_key must be unique within a plan")
        if sum(len(step.depends_on) for step in self.steps) > MAX_PLAN_EDGES:
            raise ValueError("workflow dependency count exceeds limit")
        return self


class WorkflowPlanVersionCreate(WorkflowPlanCreate):
    change_reason: ChangeReason


class WorkflowStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    step_key: str
    title: str
    step_type: WorkflowStepType
    assigned_capability: str | None
    agent_definition_id: UUID | None
    position: int
    risk_level: RiskLevel | None
    depends_on: list[str]
    created_at: datetime
    updated_at: datetime


class WorkflowPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    version: int
    title: str
    summary: str | None
    change_reason: str | None
    steps: list[WorkflowStepResponse]
    created_at: datetime
    updated_at: datetime


class WorkflowPlanListResponse(BaseModel):
    items: list[WorkflowPlanResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]


class WorkflowRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkflowStepRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workflow_step_id: UUID
    status: WorkflowStepRunStatus
    agent_run_id: UUID | None
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    workflow_plan_id: UUID
    plan_version: int
    status: WorkflowRunStatus
    correlation_id: str | None
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    step_runs: list[WorkflowStepRunResponse]
    created_at: datetime
    updated_at: datetime


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]
