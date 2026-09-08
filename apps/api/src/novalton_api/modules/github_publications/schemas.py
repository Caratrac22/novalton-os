from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA = r"^[0-9a-f]{40}$"


class GitHubPublicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=16_384)

    @field_validator("title", "body")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if (
            any(ord(c) < 32 and c not in "\n\t" for c in value)
            or not value.isprintable()
            and "\n" not in value
            and "\t" not in value
        ):
            raise ValueError("text contains unsafe control characters")
        value.encode("utf-8")
        return value


class GitHubPublicationActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    git_commit_action_id: UUID
    approval_request_id: UUID
    binding_version: str
    repository_identity: dict[str, object]
    base_branch: str
    prepared_remote_base_sha: str = Field(pattern=_SHA)
    branch_ref: str
    local_parent_sha: str = Field(pattern=_SHA)
    local_tree_sha: str = Field(pattern=_SHA)
    local_commit_sha: str = Field(pattern=_SHA)
    changeset_proof: dict[str, object]
    pr_title: str
    pr_body_hash: str
    policy_effect: Literal["REQUIRE_CONFIRMATION"]
    status: Literal[
        "PENDING_APPROVAL", "PUBLISHING", "PUBLISHED", "FAILED", "STALE", "CONFLICT", "REJECTED"
    ]
    remote_tree_sha: str | None
    remote_commit_sha: str | None
    remote_ref_sha: str | None
    pr_number: int | None
    pr_url: str | None
    failure_code: str | None
    created_at: datetime
    published_at: datetime | None
