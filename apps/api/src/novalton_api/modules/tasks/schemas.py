"""Validated public task contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TaskDescription = Annotated[str, StringConstraints(max_length=4000)]


class TaskStatus(StrEnum):
    """User-task lifecycle states established by the implementation plan."""

    BACKLOG = "BACKLOG"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskCreate(BaseModel):
    """Fields accepted when creating a task."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: TaskTitle
    description: TaskDescription | None = None
    status: TaskStatus = TaskStatus.BACKLOG

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return TaskStatus(value) if isinstance(value, str) else value


class TaskUpdate(BaseModel):
    """Fields accepted for a partial task update."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: TaskTitle | None = None
    description: TaskDescription | None = None
    status: TaskStatus | None = None

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return TaskStatus(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for field_name in {"title", "status"} & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} may not be null")
        return self


class TaskResponse(BaseModel):
    """Public task representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """Bounded task collection response."""

    items: list[TaskResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]
