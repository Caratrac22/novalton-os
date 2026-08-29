"""Bounded public and trusted-internal agent contracts."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from novalton_api.infrastructure.providers.contracts import (
    ContractEnforcementGrade,
    ExecutionTargetClass,
    QualificationSource,
)
from novalton_api.modules.agents.contracts import AgentInput, AgentResult

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class AgentDefinitionStatus(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class AgentRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DefinitionFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    status: AgentDefinitionStatus = AgentDefinitionStatus.ENABLED
    category: Identifier | None = None
    mission: str = Field(min_length=1, max_length=2000)
    capabilities: list[Identifier] = Field(default_factory=list, max_length=32)
    permissions: list[Identifier] = Field(default_factory=list, max_length=32)

    @field_validator("name", "mission")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        if value is not None and _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("category must be a normalized identifier")
        return value

    @field_validator("capabilities", "permissions")
    @classmethod
    def normalize_identifiers(cls, values: list[str]) -> list[str]:
        normalized = sorted({value.strip().lower() for value in values})
        if any(_IDENTIFIER.fullmatch(value) is None for value in normalized):
            raise ValueError("items must be normalized identifiers")
        return normalized


class AgentDefinitionCreate(DefinitionFields):
    slug: Identifier

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError("slug must be a normalized identifier")
        return value


class AgentDefinitionVersionCreate(DefinitionFields):
    pass


class AgentDefinitionResponse(DefinitionFields):
    model_config = ConfigDict(from_attributes=True, strict=False)
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    slug: str
    version: int
    created_at: datetime
    updated_at: datetime


class AgentDefinitionListResponse(BaseModel):
    items: list[AgentDefinitionResponse]
    limit: int
    offset: int


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_definition_id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    parent_agent_run_id: UUID | None = None
    model_run_id: UUID | None = None

    @model_validator(mode="after")
    def task_requires_project(self) -> "AgentRunCreate":
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task_id requires project_id")
        return self


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    task_id: UUID | None
    agent_definition_id: UUID
    agent_version: int
    agent_name: str
    agent_slug: str
    model_run_id: UUID | None
    parent_agent_run_id: UUID | None
    status: AgentRunStatus
    correlation_id: str | None
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    limit: int
    offset: int


class AgentExecutionRequest(AgentInput):
    """The I-021 input is the complete public execution request."""


class SelectedModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_model_id: UUID | None = None
    provider_id: str
    provider_model_id: str
    execution_target_class: ExecutionTargetClass
    structured_output_capability: bool
    contract_enforcement_grade: ContractEnforcementGrade
    minimum_contract_enforcement_grade: ContractEnforcementGrade
    enforcement_metadata_source: str | None = None
    qualification_present: bool = False
    qualification_source: QualificationSource | None = None
    upstream_provider_constraint: str | None = None
    provider_allow_fallbacks: bool | None = None
    provider_require_parameters: bool = False


class AgentExecutionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_run_id: UUID
    agent_definition_id: UUID
    agent_definition_version: int
    status: AgentRunStatus
    selected_model: SelectedModelResponse | None = None
    model_run_id: UUID | None = None
    result: AgentResult | None = None
    error_code: str | None = None
