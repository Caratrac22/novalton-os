"""Validated public project contracts."""

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

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ProjectSlug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
ProjectDescription = Annotated[str, StringConstraints(max_length=4000)]


class ProjectStatus(StrEnum):
    """Minimal lifecycle states established by the implementation plan."""

    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class ProjectCreate(BaseModel):
    """Fields accepted when creating a project."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: ProjectName
    slug: ProjectSlug
    description: ProjectDescription | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return ProjectStatus(value) if isinstance(value, str) else value


class ProjectUpdate(BaseModel):
    """Fields accepted for a partial project update."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: ProjectName | None = None
    slug: ProjectSlug | None = None
    description: ProjectDescription | None = None
    status: ProjectStatus | None = None

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return ProjectStatus(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for field_name in {"name", "slug", "status"} & self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} may not be null")
        return self


class ProjectResponse(BaseModel):
    """Public project representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    """Bounded project collection response."""

    items: list[ProjectResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]
