"""Validated internal runtime event contracts."""

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_PAYLOAD_BYTES = 8 * 1024


class RuntimeEventCreate(BaseModel):
    """Fields accepted by the internal append operation."""

    model_config = ConfigDict(extra="forbid", strict=True, arbitrary_types_allowed=False)

    tenant_id: UUID
    workspace_id: UUID
    event_type: str = Field(min_length=3, max_length=100)
    source: str = Field(min_length=1, max_length=64)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    project_id: UUID | None = None
    task_id: UUID | None = None
    payload: dict[str, Any] | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if EVENT_TYPE_PATTERN.fullmatch(value) is None:
            raise ValueError("event_type must be lowercase dot-separated identifiers")
        return value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if SOURCE_PATTERN.fullmatch(value) is None:
            raise ValueError("source must be a lowercase identifier")
        return value

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, value: str | None) -> str | None:
        if value is not None and CORRELATION_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("correlation_id contains unsupported characters")
        return value
