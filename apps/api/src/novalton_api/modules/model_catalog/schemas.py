"""Strict catalog API and persistence-facing contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ProviderIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
    ),
]


class ModelStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider_id: ProviderIdentifier


class ModelDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: str
    provider_model_id: str
    display_name: str
    status: ModelStatus
    context_window: int | None
    max_output_tokens: int | None
    reasoning: bool | None
    coding: bool | None
    tool_calling: bool | None
    structured_output: bool | None
    vision: bool | None
    input_price_per_million: Decimal | None
    output_price_per_million: Decimal | None
    currency: str | None
    free_allowlisted: bool
    family: str | None
    revision: str | None
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelDefinitionListResponse(BaseModel):
    items: list[ModelDefinitionResponse]
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0)]


class RefreshResponse(BaseModel):
    provider_id: str
    verified_count: Annotated[int, Field(ge=0)]
    stale_count: Annotated[int, Field(ge=0)]
    verified_at: datetime


class ModelFilters(BaseModel):
    model_config = ConfigDict(strict=True)

    provider_id: ProviderIdentifier | None = None
    status: ModelStatus | None = None

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, value: object) -> object:
        return ModelStatus(value) if isinstance(value, str) else value
