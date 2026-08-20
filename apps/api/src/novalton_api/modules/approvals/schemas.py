"""Strict contracts for one-action approval requests and decisions."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from novalton_api.modules.policy.schemas import ACTION, TYPE_IDENTIFIER, PolicyEvaluationContext

ActorReference = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]
_SECRET_REFERENCE = re.compile(r"(?:^(?:bearer|basic)[._:-]|^sk-[A-Za-z0-9_-]{8,}$)", re.IGNORECASE)


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalScopeType(StrEnum):
    ONE_ACTION = "ONE_ACTION"


class ApprovalCreate(BaseModel):
    """A proposed action that the server must independently evaluate."""

    model_config = ConfigDict(extra="forbid", strict=True)

    action: str = Field(min_length=3, max_length=100)
    requester_actor_type: Literal["api", "agent", "model", "service", "tool"]
    requester_actor_id: ActorReference | None = None
    resource_type: str | None = Field(default=None, min_length=1, max_length=64)
    resource_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    scope_type: Literal[ApprovalScopeType.ONE_ACTION] = ApprovalScopeType.ONE_ACTION
    context: PolicyEvaluationContext = Field(default_factory=PolicyEvaluationContext)

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        if ACTION.fullmatch(value) is None:
            raise ValueError("action must be a lowercase dot-separated identifier")
        return value

    @field_validator("requester_actor_id")
    @classmethod
    def reject_credential_reference(cls, value: str | None) -> str | None:
        if value is not None and _SECRET_REFERENCE.search(value):
            raise ValueError("requester actor reference contains credential material")
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.resource_type is not None and TYPE_IDENTIFIER.fullmatch(self.resource_type) is None:
            raise ValueError("resource_type must be a lowercase identifier")
        if (self.resource_type is None) != (self.resource_id is None):
            raise ValueError("resource_type and resource_id must be supplied together")
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task_id requires project_id")
        if self.resource_type == "project" and self.resource_id != self.project_id:
            raise ValueError("project resource must match project_id")
        if self.resource_type == "task" and self.resource_id != self.task_id:
            raise ValueError("task resource must match task_id")
        return self


class ApprovalResponse(BaseModel):
    """Safe persisted authority record exposed to callers."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    action: str
    requester_actor_type: str
    requester_actor_id: str | None
    resource_type: str | None
    resource_id: UUID | None
    project_id: UUID | None
    task_id: UUID | None
    status: ApprovalStatus
    scope_type: ApprovalScopeType
    policy_effect: Literal["REQUIRE_CONFIRMATION"]
    matched_rule_ids: list[str]
    policy_reasons: list[str]
    decision_actor_type: Literal["local_user"] | None
    decision_actor_id: None
    requested_at: datetime
    decided_at: datetime | None
    correlation_id: str | None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]
