"""Strict bounded workflow API and internal lifecycle contracts."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.agents.contracts import AgentResultStatus, ChallengeLevel
from novalton_api.modules.agents.schemas import AgentRunStatus
from novalton_api.modules.model_usage.schemas import ModelRunStatus
from novalton_api.modules.policy.schemas import PolicyEffect
from novalton_api.modules.qa_worker.contracts import QAVerdict

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
ChangeReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
StepKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Capability = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

MAX_PLAN_STEPS = 100
MAX_PLAN_EDGES = 500
_UNSAFE_HANDOFF = re.compile(
    r"(?:https?://|data:|;base64,|```|\$\(|&&|\|\||\b(?:sudo|curl|wget)\s)", re.IGNORECASE
)


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


class DevelopmentWorkflowCreate(BaseModel):
    """Trusted bounded input for the fixed I-028 graph."""

    model_config = ConfigDict(extra="forbid", strict=True)
    objective: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1500)
    ]
    acceptance_criteria: Annotated[
        list[
            Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
        ],
        Field(min_length=1, max_length=24),
    ]

    @field_validator("objective")
    @classmethod
    def safe_objective(cls, value: str) -> str:
        if _UNSAFE_HANDOFF.search(value):
            raise ValueError("executable or externally addressed content is not allowed")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def safe_criteria(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate acceptance criterion")
        if any(_UNSAFE_HANDOFF.search(value) for value in values):
            raise ValueError("executable or externally addressed content is not allowed")
        return values


class DevelopmentWorkflowResponse(BaseModel):
    workflow_plan: WorkflowPlanResponse
    workflow_run: WorkflowRunResponse


class OperatorChallengeResponse(BaseModel):
    """Safe persisted challenge facts; agent and human free text are intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_level: ChallengeLevel
    result_status: AgentResultStatus
    specialization_role: Literal["developer_manager", "developer_worker", "qa_worker"] | None
    qa_verdict: QAVerdict | None
    decision: Literal["ACCEPT_RESULT", "REJECT_RESULT"] | None
    decided_at: datetime | None


class OperatorModelRunResponse(BaseModel):
    """Bounded accounting and route identity for one provider attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    status: ModelRunStatus
    provider_id: str
    provider_model_id: str
    execution_target_class: ExecutionTargetClass | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: float | None
    failure_code: str | None
    recovery_attempt_kind: Literal["INITIAL", "TRUNCATION", "CONTRACT_REPAIR", "TOOL_CONTINUATION"]
    recovery_attempt_index: int


class OperatorToolCallResponse(BaseModel):
    """Safe tool activity with no input query or file body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tool_name: str
    status: Literal["PROPOSED", "PENDING_APPROVAL", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED"]
    policy_effect: PolicyEffect | None
    approval_request_id: UUID | None
    execution_target_class: Literal["LOCAL"]
    duration_ms: float | None
    result_count: int | None
    bytes_returned: int | None
    truncated: bool | None
    failure_code: str | None


class OperatorAgentRunResponse(BaseModel):
    """Safe AgentRun lifecycle fields and its bounded model-attempt diagnostics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    status: AgentRunStatus
    agent_name: str
    agent_slug: str
    failure_code: str | None
    model_runs: list[OperatorModelRunResponse]
    tool_calls: list[OperatorToolCallResponse]


class OperatorStepDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_step_run_id: UUID
    specialization_role: Literal["developer_manager", "developer_worker", "qa_worker"] | None
    challenge: OperatorChallengeResponse | None
    agent_run: OperatorAgentRunResponse | None


class OperatorWorkflowRunResponse(BaseModel):
    """Minimal workflow lifecycle state without request-correlation or scope internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    task_id: UUID
    workflow_plan_id: UUID
    plan_version: int
    status: WorkflowRunStatus
    failure_code: str | None
    step_runs: list[WorkflowStepRunResponse]


class OperatorWorkflowResponse(BaseModel):
    """Read-only operator projection over authoritative persisted workflow state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_plan: WorkflowPlanResponse
    workflow_run: OperatorWorkflowRunResponse
    step_details: list[OperatorStepDetailResponse]
    qa_verdict: QAVerdict | None
