"""Strict internal policy persistence and evaluation contracts."""

import re
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ACTION_PATTERN = re.compile(r"^(?:\*|[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*(?:\.\*)?)$")
ACTION = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
TYPE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ENVIRONMENT = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

PolicyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    ALLOW_WITH_LOG = "ALLOW_WITH_LOG"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    BLOCK = "BLOCK"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyCondition(BaseModel):
    """One bounded condition over an explicitly trusted context attribute."""

    model_config = ConfigDict(extra="forbid", strict=True)

    field: Literal["risk_level", "environment", "reversible"]
    operator: Literal["equals", "in"]
    value: str | bool | list[str]

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if self.operator == "in":
            if not isinstance(self.value, list) or not 1 <= len(self.value) <= 8:
                raise ValueError("in requires between one and eight string values")
        elif isinstance(self.value, list):
            raise ValueError("equals requires a scalar value")

        values = self.value if isinstance(self.value, list) else [self.value]
        if self.field == "reversible":
            if self.operator != "equals" or not isinstance(self.value, bool):
                raise ValueError("reversible supports only equals with a boolean")
        elif not all(isinstance(item, str) for item in values):
            raise ValueError(f"{self.field} requires string values")
        elif self.field == "risk_level" and any(
            item not in {level.value for level in RiskLevel} for item in values
        ):
            raise ValueError("unsupported risk_level")
        elif self.field == "environment" and any(
            ENVIRONMENT.fullmatch(item) is None for item in values
        ):
            raise ValueError("unsupported environment")
        return self


class PolicyRuleCreate(BaseModel):
    """Validated data for a persistent rule."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID
    workspace_id: UUID | None = None
    name: PolicyName
    enabled: bool = True
    action_pattern: str = Field(min_length=1, max_length=100)
    effect: PolicyEffect
    actor_type: str | None = Field(default=None, min_length=1, max_length=64)
    resource_type: str | None = Field(default=None, min_length=1, max_length=64)
    conditions: list[PolicyCondition] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_identifiers(self) -> Self:
        if ACTION_PATTERN.fullmatch(self.action_pattern) is None:
            raise ValueError("action_pattern must be exact, '*', or a terminal namespace wildcard")
        for value in (self.actor_type, self.resource_type):
            if value is not None and TYPE_IDENTIFIER.fullmatch(value) is None:
                raise ValueError("actor_type and resource_type must be lowercase identifiers")
        return self


class PolicyEvaluationContext(BaseModel):
    """Only context fields whose provenance a caller must establish outside the engine."""

    model_config = ConfigDict(extra="forbid", strict=True)

    risk_level: RiskLevel | None = None
    environment: str | None = Field(default=None, min_length=1, max_length=32)
    reversible: bool | None = None

    @model_validator(mode="after")
    def validate_environment(self) -> Self:
        if self.environment is not None and ENVIRONMENT.fullmatch(self.environment) is None:
            raise ValueError("unsupported environment")
        return self


class PolicyEvaluationRequest(BaseModel):
    """Transport-independent input to deterministic evaluation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: UUID
    workspace_id: UUID
    action: str = Field(min_length=3, max_length=100)
    actor_type: str | None = Field(default=None, min_length=1, max_length=64)
    actor_id: str | None = Field(default=None, min_length=1, max_length=128)
    resource_type: str | None = Field(default=None, min_length=1, max_length=64)
    resource_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    context: PolicyEvaluationContext = Field(default_factory=PolicyEvaluationContext)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if ACTION.fullmatch(self.action) is None:
            raise ValueError("action must be a lowercase dot-separated identifier")
        for value in (self.actor_type, self.resource_type):
            if value is not None and TYPE_IDENTIFIER.fullmatch(value) is None:
                raise ValueError("actor_type and resource_type must be lowercase identifiers")
        if (self.resource_type is None) != (self.resource_id is None):
            raise ValueError("resource_type and resource_id must be supplied together")
        if self.actor_id is not None and self.actor_type is None:
            raise ValueError("actor_id requires actor_type")
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task_id requires project_id")
        if self.resource_type == "project" and self.resource_id != self.project_id:
            raise ValueError("project resource must match project_id")
        if self.resource_type == "task" and self.resource_id != self.task_id:
            raise ValueError("task resource must match task_id")
        return self


class PolicyEvaluationResult(BaseModel):
    """Explainable authoritative decision without caller-controlled flags."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    effect: PolicyEffect
    matched_rule_ids: list[UUID]
    matched_rule_names: list[str]
    reasons: list[str]
    confirmation_required: bool
    audit_required: bool
