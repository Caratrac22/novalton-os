"""Bounded public contract for one deterministic orchestration cycle."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from novalton_api.modules.agents.contracts import ChallengeLevel, _safe_text
from novalton_api.modules.workflows.schemas import WorkflowRunStatus, WorkflowStepRunStatus


class OrchestrationOutcome(StrEnum):
    STEP_COMPLETED = "STEP_COMPLETED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    NO_RUNNABLE_STEP = "NO_RUNNABLE_STEP"
    CANCELLED = "CANCELLED"


class OrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_run_id: UUID
    workflow_status: WorkflowRunStatus
    workflow_step_run_id: UUID | None = None
    step_key: str | None = None
    agent_run_id: UUID | None = None
    step_status: WorkflowStepRunStatus | None = None
    outcome: OrchestrationOutcome
    reason_code: str | None = None
    challenge_level: ChallengeLevel | None = None
    remaining_ready: int
    remaining_pending: int


class ChallengeResolutionDecision(StrEnum):
    ACCEPT_RESULT = "ACCEPT_RESULT"
    REJECT_RESULT = "REJECT_RESULT"


class ChallengeResolutionRequest(BaseModel):
    """The only caller-authored fields accepted by the trusted local-human route."""

    model_config = ConfigDict(extra="forbid", strict=True)

    decision: ChallengeResolutionDecision
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("decision", mode="before")
    @classmethod
    def parse_decision(cls, value: object) -> object:
        return ChallengeResolutionDecision(value) if isinstance(value, str) else value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        return _safe_text(value) if value is not None else None


class ChallengeResolutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resolution_id: UUID
    workflow_run_id: UUID
    workflow_step_run_id: UUID
    agent_run_id: UUID
    challenge_level: ChallengeLevel
    decision: ChallengeResolutionDecision
    decision_actor_type: Literal["local_user"]
    decided_at: datetime
    workflow_status: WorkflowRunStatus
    step_status: WorkflowStepRunStatus
    outcome: OrchestrationOutcome
    reason_code: str | None = None
