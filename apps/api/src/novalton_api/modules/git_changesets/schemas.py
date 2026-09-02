"""Closed operator contracts for local Git changesets."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GitCommitPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    commit_message: str = Field(min_length=1, max_length=200)

    @field_validator("commit_message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value or any(ord(item) < 32 for item in value):
            raise ValueError("commit message must be bounded single-line printable text")
        return value


class GitCommitActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workflow_run_id: UUID
    branch_ref: str
    prepared_head_sha: str
    source_tool_call_ids: list[str]
    prepared_paths: list[dict[str, object]]
    preview: dict[str, object]
    commit_message: str
    action_fingerprint: str
    policy_effect: Literal["REQUIRE_CONFIRMATION"]
    approval_request_id: UUID | None
    status: Literal["PENDING_APPROVAL", "APPLYING", "APPLIED", "FAILED", "REJECTED"]
    resulting_commit_sha: str | None
    failure_code: str | None
    created_at: datetime
    applied_at: datetime | None
