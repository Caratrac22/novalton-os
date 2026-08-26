"""Strict internal and diagnostic model-run contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from novalton_api.infrastructure.providers.contracts import ContractEnforcementGrade


class ModelRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


Currency = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=3)]


class ModelRunStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model_definition_id: UUID | None = None
    provider_id: str | None = None
    provider_model_id: str | None = None
    agent_run_id: UUID | None = None
    project_id: UUID | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=10)
    currency: Currency | None = None
    target_structured_output_capability: bool = False
    contract_enforcement_grade: ContractEnforcementGrade = ContractEnforcementGrade.UNSUPPORTED
    minimum_contract_enforcement_grade: ContractEnforcementGrade = (
        ContractEnforcementGrade.UNSUPPORTED
    )
    enforcement_metadata_source: str | None = Field(default=None, min_length=1, max_length=64)
    contract_strategy_tier: str | None = Field(
        default=None, pattern=r"^(STRICT_SCHEMA|JSON_OBJECT|JSON_INSTRUCTION)$"
    )
    contract_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,64}$")
    contextual_constraint_count: int | None = Field(default=None, ge=0, le=16)
    execution_max_output_tokens: int | None = Field(default=None, ge=1, le=65_536)
    output_budget_source: str | None = Field(default=None, pattern=r"^[a-z_]{1,64}$")
    recovery_attempt_kind: str = Field(
        default="INITIAL", pattern=r"^(INITIAL|TRUNCATION|CONTRACT_REPAIR)$"
    )
    recovery_attempt_index: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_estimate(self) -> "ModelRunStart":
        if self.model_definition_id is None and (
            self.provider_id is None or self.provider_model_id is None
        ):
            raise ValueError("a catalog model or explicit provider route is required")
        if (self.estimated_cost is None) != (self.currency is None):
            raise ValueError("estimated_cost and currency must be supplied together")
        if self.currency is not None and self.currency != self.currency.upper():
            raise ValueError("currency must be uppercase")
        return self


class ModelRunExecutionDiagnostics(BaseModel):
    """Safe contract and budget facts known before one provider generation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract_strategy_tier: str = Field(pattern=r"^(STRICT_SCHEMA|JSON_OBJECT|JSON_INSTRUCTION)$")
    contract_fingerprint: str = Field(pattern=r"^[a-f0-9]{8,64}$")
    contextual_constraint_count: int = Field(ge=0, le=16)
    execution_max_output_tokens: int = Field(ge=1, le=65_536)
    output_budget_source: str = Field(pattern=r"^[a-z_]{1,64}$")


class ModelRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    agent_run_id: UUID | None
    model_definition_id: UUID | None
    provider_id: str
    provider_model_id: str
    target_structured_output_capability: bool
    contract_enforcement_grade: ContractEnforcementGrade
    minimum_contract_enforcement_grade: ContractEnforcementGrade
    enforcement_metadata_source: str | None
    contract_strategy_tier: str | None
    contract_fingerprint: str | None
    contextual_constraint_count: int | None
    execution_max_output_tokens: int | None
    output_budget_source: str | None
    finish_reason: str | None
    truncation_classification: str
    recovery_attempt_kind: str
    recovery_attempt_index: int
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
