"""Strict public contracts for model routing simulation."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from novalton_api.modules.model_catalog.schemas import ProviderIdentifier


class ModelCapability(StrEnum):
    REASONING = "reasoning"
    CODING = "coding"
    TOOL_CALLING = "tool_calling"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"


class CostPolicy(StrEnum):
    LOWEST_COST = "LOWEST_COST"
    PREFER_FREE = "PREFER_FREE"
    FREE_ONLY = "FREE_ONLY"


class RoutingOutcome(StrEnum):
    SELECTED = "SELECTED"
    NO_SUITABLE_MODEL = "NO_SUITABLE_MODEL"


class RoutingReason(StrEnum):
    AVAILABLE = "AVAILABLE"
    CAPABILITIES_SATISFIED = "CAPABILITIES_SATISFIED"
    CONTEXT_SATISFIED = "CONTEXT_SATISFIED"
    PREFERRED_MODEL_ACCEPTED = "PREFERRED_MODEL_ACCEPTED"
    PREFERRED_MODEL_REJECTED = "PREFERRED_MODEL_REJECTED"
    FREE_ALLOWLIST_PREFERRED = "FREE_ALLOWLIST_PREFERRED"
    FREE_ONLY_SATISFIED = "FREE_ONLY_SATISFIED"
    LOWEST_KNOWN_ESTIMATED_COST = "LOWEST_KNOWN_ESTIMATED_COST"
    PRICING_UNKNOWN_DETERMINISTIC_SELECTION = "PRICING_UNKNOWN_DETERMINISTIC_SELECTION"
    PROVIDER_PREFERENCE_APPLIED = "PROVIDER_PREFERENCE_APPLIED"
    DETERMINISTIC_ID_TIE_BREAK = "DETERMINISTIC_ID_TIE_BREAK"
    NO_AVAILABLE_MODELS = "NO_AVAILABLE_MODELS"
    CONTEXT_UNSATISFIED = "CONTEXT_UNSATISFIED"
    CAPABILITY_UNSATISFIED = "CAPABILITY_UNSATISFIED"
    FREE_ONLY_POOL_EMPTY = "FREE_ONLY_POOL_EMPTY"


class RoutingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    required_capabilities: list[ModelCapability] = Field(max_length=5)
    context_tokens_estimate: int = Field(ge=1, le=10_000_000)
    tool_calling_required: bool = False
    structured_output_required: bool = False
    vision_required: bool = False
    expected_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    cost_policy: CostPolicy = CostPolicy.LOWEST_COST
    preferred_provider: ProviderIdentifier | None = None
    preferred_model_id: UUID | None = None

    @field_validator("cost_policy", mode="before")
    @classmethod
    def parse_cost_policy(cls, value: object) -> object:
        return CostPolicy(value) if isinstance(value, str) else value

    @field_validator("preferred_model_id", mode="before")
    @classmethod
    def parse_preferred_model_id(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def parse_capabilities(cls, value: object) -> object:
        if isinstance(value, list):
            return [ModelCapability(item) if isinstance(item, str) else item for item in value]
        return value

    @field_validator("required_capabilities")
    @classmethod
    def reject_duplicate_capabilities(cls, value: list[ModelCapability]) -> list[ModelCapability]:
        if len(value) != len(set(value)):
            raise ValueError("required_capabilities must not contain duplicates")
        return value


class EstimatedCost(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: Annotated[str, StringConstraints(min_length=3, max_length=3)]
    input_tokens_estimate: int
    output_tokens_estimate: int | None
    is_estimate: bool = True


class SelectedCatalogModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog_model_id: UUID
    provider_id: str
    provider_model_id: str
    display_name: str
    last_verified_at: datetime | None
    estimated_cost: EstimatedCost | None


class RoutingSimulationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: RoutingOutcome
    selected: SelectedCatalogModel | None
    reason_codes: list[RoutingReason]
    eligible_candidate_count: Annotated[int, Field(ge=0)]
