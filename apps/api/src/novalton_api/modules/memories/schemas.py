"""Validated public contracts for structured memory."""

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

MemoryStatement = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
MemoryQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
SourceReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]


class MemoryKind(StrEnum):
    FACT = "FACT"
    DECISION = "DECISION"
    PREFERENCE = "PREFERENCE"
    CONSTRAINT = "CONSTRAINT"
    EVENT = "EVENT"
    NOTE = "NOTE"


class KnowledgeState(StrEnum):
    CONFIRMED_FACT = "CONFIRMED_FACT"
    OBSERVED_FACT = "OBSERVED_FACT"
    INFERENCE = "INFERENCE"
    HYPOTHESIS = "HYPOTHESIS"
    DISPUTED = "DISPUTED"
    OBSOLETE = "OBSOLETE"


class MemoryLifecycle(StrEnum):
    """Availability state, not a claim about whether the memory is true."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MemorySensitivity(StrEnum):
    """Human-facing sensitivity label; disclosure is governed by ``model_access``."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"


class MemoryModelAccess(StrEnum):
    """Provider-neutral hard boundary for model disclosure."""

    LOCAL_ONLY = "LOCAL_ONLY"
    LOCAL_AND_REMOTE = "LOCAL_AND_REMOTE"


class ProvenanceSourceType(StrEnum):
    USER_STATEMENT = "USER_STATEMENT"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    DOCUMENT = "DOCUMENT"
    AGENT_RESULT = "AGENT_RESULT"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    DERIVED_FROM_MEMORY = "DERIVED_FROM_MEMORY"
    MANUAL_EDIT = "MANUAL_EDIT"


class MemoryProvenanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_type: ProvenanceSourceType
    source_reference_id: SourceReference | None = None

    @field_validator("source_type", mode="before")
    @classmethod
    def parse_source_type(cls, value: object) -> object:
        return ProvenanceSourceType(value) if isinstance(value, str) else value


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    task_id: UUID | None = None
    workflow_run_id: UUID | None = None
    kind: MemoryKind
    knowledge_state: KnowledgeState
    statement: MemoryStatement
    confidence: Annotated[float, Field(ge=0, le=1)]
    importance: Annotated[int, Field(ge=1, le=5)]
    valid_from: datetime
    valid_to: datetime | None = None
    lifecycle: MemoryLifecycle = MemoryLifecycle.ACTIVE
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    model_access: MemoryModelAccess = MemoryModelAccess.LOCAL_ONLY
    provenance: Annotated[list[MemoryProvenanceCreate], Field(min_length=1, max_length=16)]

    @field_validator("kind", mode="before")
    @classmethod
    def parse_kind(cls, value: object) -> object:
        return MemoryKind(value) if isinstance(value, str) else value

    @field_validator("knowledge_state", mode="before")
    @classmethod
    def parse_knowledge_state(cls, value: object) -> object:
        return KnowledgeState(value) if isinstance(value, str) else value

    @field_validator("lifecycle", mode="before")
    @classmethod
    def parse_lifecycle(cls, value: object) -> object:
        return MemoryLifecycle(value) if isinstance(value, str) else value

    @field_validator("sensitivity", mode="before")
    @classmethod
    def parse_sensitivity(cls, value: object) -> object:
        return MemorySensitivity(value) if isinstance(value, str) else value

    @field_validator("model_access", mode="before")
    @classmethod
    def parse_model_access(cls, value: object) -> object:
        return MemoryModelAccess(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_shape(self) -> "MemoryCreate":
        if self.valid_from.tzinfo is None or (
            self.valid_to is not None and self.valid_to.tzinfo is None
        ):
            raise ValueError("temporal values must include a timezone")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task_id requires project_id")
        if (
            self.sensitivity == MemorySensitivity.RESTRICTED
            and self.model_access != MemoryModelAccess.LOCAL_ONLY
        ):
            raise ValueError("RESTRICTED memory requires LOCAL_ONLY model_access")
        return self


class MemoryProvenanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: ProvenanceSourceType
    source_reference_id: str | None
    created_at: datetime


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    task_id: UUID | None
    workflow_run_id: UUID | None
    kind: MemoryKind
    knowledge_state: KnowledgeState
    statement: str
    confidence: float
    importance: int
    valid_from: datetime
    valid_to: datetime | None
    lifecycle: MemoryLifecycle
    sensitivity: MemorySensitivity = MemorySensitivity.INTERNAL
    model_access: MemoryModelAccess = MemoryModelAccess.LOCAL_ONLY
    created_at: datetime
    updated_at: datetime
    provenance: list[MemoryProvenanceResponse]


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]


class MemoryRetrievalRequest(BaseModel):
    """Bounded, provider-neutral context retrieval constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: MemoryQuery | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    workflow_run_id: UUID | None = None
    kinds: Annotated[tuple[MemoryKind, ...] | None, Field(max_length=6)] = None
    knowledge_states: Annotated[tuple[KnowledgeState, ...] | None, Field(max_length=6)] = None
    lifecycle: Annotated[tuple[MemoryLifecycle, ...] | None, Field(max_length=2)] = None
    as_of: datetime | None = None
    min_confidence: Annotated[float | None, Field(ge=0, le=1)] = None
    min_importance: Annotated[int | None, Field(ge=1, le=5)] = None
    limit: Annotated[int, Field(ge=1, le=50)] = 10

    @model_validator(mode="after")
    def validate_retrieval_shape(self) -> "MemoryRetrievalRequest":
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return self


class MemoryRetrievalResult(MemoryResponse):
    lexical_relevance: float | None = None


class MemoryRetrievalResponse(BaseModel):
    items: list[MemoryRetrievalResult]
    limit: Annotated[int, Field(ge=1, le=50)]
    as_of: datetime
