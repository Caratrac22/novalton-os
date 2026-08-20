"""Strict internal contracts for accountability audit records."""

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_METADATA_BYTES = 4 * 1024

ActorType = Literal["system", "api", "local_user", "service"]
AuditOutcome = Literal["success", "failure", "blocked", "cancelled"]
ResourceType = Literal["project", "task"]


class AuditRecordCreate(BaseModel):
    """Fields accepted by the internal append operation."""

    model_config = ConfigDict(extra="forbid", strict=True, arbitrary_types_allowed=False)

    tenant_id: UUID
    workspace_id: UUID
    action: str = Field(min_length=3, max_length=100)
    actor_type: ActorType
    actor_id: str | None = Field(default=None, min_length=1, max_length=128)
    outcome: AuditOutcome
    resource_type: ResourceType | None = None
    resource_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    metadata: dict[str, Any] | None = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        if ACTION_PATTERN.fullmatch(value) is None:
            raise ValueError("action must be lowercase dot-separated identifiers")
        return value

    @field_validator("actor_id", "correlation_id")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        if value is not None and REFERENCE_PATTERN.fullmatch(value) is None:
            raise ValueError("reference contains unsupported characters")
        return value
