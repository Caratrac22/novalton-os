"""Strict internal and diagnostic model-run contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ModelRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


Currency = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=3)]


class ModelRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model_definition_id: UUID
    agent_run_id: UUID | None = None
    project_id: UUID | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=10)
    currency: Currency | None = None

    @model_validator(mode="after")
    def validate_estimate(self) -> "ModelRunStart":
        if (self.estimated_cost is None) != (self.currency is None):
            raise ValueError("estimated_cost and currency must be supplied together")
        if self.currency is not None and self.currency != self.currency.upper():
            raise ValueError("currency must be uppercase")
        return self


class ModelRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    agent_run_id: UUID | None
    model_definition_id: UUID
    provider_id: str
    provider_model_id: str
    provider_resolved_model_id: str | None
    status: ModelRunStatus
    correlation_id: str | None
    provider_request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    estimated_cost: Decimal | None
    actual_cost: Decimal | None
    input_price_per_million_snapshot: Decimal | None
    output_price_per_million_snapshot: Decimal | None
    currency: str | None
    duration_ms: Decimal | None
    failure_code: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelRunListResponse(BaseModel):
    items: list[ModelRunResponse]
    limit: int
    offset: int
