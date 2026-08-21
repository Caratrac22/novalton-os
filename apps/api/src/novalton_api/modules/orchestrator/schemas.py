"""Bounded public contract for one deterministic orchestration cycle."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from novalton_api.modules.agents.contracts import ChallengeLevel
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
