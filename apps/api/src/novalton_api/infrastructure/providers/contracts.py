"""Strict provider-neutral text generation contracts."""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from novalton_api.core.limits import MAX_CATALOG_OUTPUT_TOKENS, MAX_EXECUTION_OUTPUT_TOKENS

MAX_MESSAGES = 128
MAX_MESSAGE_CHARACTERS = 65_536
MAX_REQUEST_CHARACTERS = 262_144
MAX_RESULT_CHARACTERS = 1_048_576
MAX_SCHEMA_NAME_CHARACTERS = 64
MODEL_ID_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}|~[A-Za-z0-9][A-Za-z0-9._:/+-]{0,254})$"
)
PROVIDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
UPSTREAM_PROVIDER_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,63})?$"
)

ModelIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]


class ContractEnforcementGrade(StrEnum):
    """Provider-neutral strength of structured contract enforcement.

    Capability support answers whether a target accepts structured-output requests. This grade
    separately records the strongest enforcement claim backed by trustworthy metadata.
    """

    UNSUPPORTED = "UNSUPPORTED"
    BEST_EFFORT = "BEST_EFFORT"
    PROVIDER_ENFORCED = "PROVIDER_ENFORCED"
    STRICT_SCHEMA_GUARANTEED = "STRICT_SCHEMA_GUARANTEED"

    @property
    def rank(self) -> int:
        return {
            ContractEnforcementGrade.UNSUPPORTED: 0,
            ContractEnforcementGrade.BEST_EFFORT: 1,
            ContractEnforcementGrade.PROVIDER_ENFORCED: 2,
            ContractEnforcementGrade.STRICT_SCHEMA_GUARANTEED: 3,
        }[self]

    def satisfies(self, minimum: "ContractEnforcementGrade") -> bool:
        return self.rank >= minimum.rank


class QualificationSource(StrEnum):
    """Trusted provenance for an explicit governed target qualification."""

    PROVIDER_DOCUMENTATION = "PROVIDER_DOCUMENTATION"
    OPERATOR_CONFIGURATION = "OPERATOR_CONFIGURATION"
    CURATED_REGISTRY = "CURATED_REGISTRY"


class GovernedProviderQualification(BaseModel):
    """A bounded provider-neutral policy overlay for one catalog model identity.

    It deliberately does not mutate catalog capability metadata. The router applies it only to
    catalog targets, never to provider-managed dynamic routes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z][a-z0-9_-]{0,63}$",
        ),
    ]
    provider_model_id: ModelIdentifier
    upstream_provider: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
        ]
        | None
    ) = None
    contract_enforcement_grade: ContractEnforcementGrade
    qualification_source: QualificationSource
    enabled: bool = True

    @model_validator(mode="after")
    def validate_qualification(self) -> Self:
        if MODEL_ID_PATTERN.fullmatch(self.provider_model_id) is None:
            raise ValueError("provider_model_id contains unsupported characters")
        if (
            self.upstream_provider is not None
            and UPSTREAM_PROVIDER_PATTERN.fullmatch(self.upstream_provider) is None
        ):
            raise ValueError("upstream_provider contains unsupported characters")
        if not self.contract_enforcement_grade.satisfies(
            ContractEnforcementGrade.PROVIDER_ENFORCED
        ):
            raise ValueError("governed qualification requires provider-enforced grade")
        return self


class CatalogModel(BaseModel):
    """One provider-normalized catalog entry with no raw metadata attached."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_model_id: ModelIdentifier
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=MAX_CATALOG_OUTPUT_TOKENS)
    reasoning: bool | None = None
    coding: bool | None = None
    tool_calling: bool | None = None
    structured_output: bool | None = None
    contract_enforcement_grade: ContractEnforcementGrade | None = None
    enforcement_metadata_source: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None
    ) = None
    vision: bool | None = None
    input_price_per_million: Decimal | None = Field(
        default=None, ge=0, max_digits=20, decimal_places=10
    )
    output_price_per_million: Decimal | None = Field(
        default=None, ge=0, max_digits=20, decimal_places=10
    )
    currency: Annotated[str, StringConstraints(min_length=3, max_length=3)] | None = None
    family: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    revision: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None

    @model_validator(mode="after")
    def validate_catalog_model(self) -> Self:
        if MODEL_ID_PATTERN.fullmatch(self.provider_model_id) is None:
            raise ValueError("provider_model_id contains unsupported characters")
        if self.currency is not None and self.currency != self.currency.upper():
            raise ValueError("currency must be an uppercase ISO-style code")
        if self.currency is not None and (
            self.input_price_per_million is None and self.output_price_per_million is None
        ):
            raise ValueError("currency requires known pricing")
        if self.currency is None and (
            self.input_price_per_million is not None or self.output_price_per_million is not None
        ):
            raise ValueError("known pricing requires a reliable currency")
        if (
            self.contract_enforcement_grade is not None
            and self.contract_enforcement_grade != ContractEnforcementGrade.UNSUPPORTED
            and self.structured_output is not True
        ):
            raise ValueError("contract enforcement requires structured output support")
        return self


@dataclass(frozen=True)
class ProviderManagedRoute:
    """An explicitly registered provider route which is not a catalog model."""

    provider_id: str
    provider_model_id: str
    display_name: str
    enabled: bool = True
    capabilities: frozenset[str] = frozenset()
    capability_policy: str = "DECLARED_GUARANTEE"
    contract_enforcement_grade: ContractEnforcementGrade = ContractEnforcementGrade.UNSUPPORTED
    enforcement_metadata_source: str = "provider_adapter"
    context_window: int | None = None
    max_output_tokens: int | None = None
    pricing_policy: str | None = None
    free_allowlisted: bool = False
    dynamic_resolution: bool = True
    source: str = "provider_adapter"
    capability_source: str = "provider_adapter"


MessageContent = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_MESSAGE_CHARACTERS),
]


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """One ordered, textual chat message with an explicit common role."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: MessageRole
    content: MessageContent


class StructuredOutputRequest(BaseModel):
    """Provider-neutral request for a strict JSON Schema-shaped response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_SCHEMA_NAME_CHARACTERS
        ),
    ]
    json_schema: dict[str, Any] = Field(min_length=1)
    strict: bool = True

    @model_validator(mode="after")
    def validate_schema_name(self) -> Self:
        if SCHEMA_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("structured output name contains unsupported characters")
        return self


class JsonObjectRequest(BaseModel):
    """Provider-neutral request for JSON object response formatting."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = True


class ProviderRequestOptions(BaseModel):
    """Provider-neutral request metadata for adapter protocol mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    require_parameters: bool = False
    response_healing: bool = False
    upstream_provider: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
        ]
        | None
    ) = None
    allow_fallbacks: bool | None = None

    @model_validator(mode="after")
    def validate_upstream_constraint(self) -> Self:
        if self.upstream_provider is not None:
            if UPSTREAM_PROVIDER_PATTERN.fullmatch(self.upstream_provider) is None:
                raise ValueError("upstream_provider contains unsupported characters")
            if self.allow_fallbacks is not False or not self.require_parameters:
                raise ValueError(
                    "upstream provider constraints require no fallback and required parameters"
                )
        return self


@dataclass(frozen=True)
class ProviderExecutionCapabilities:
    """Provider-neutral features supported by an adapter at execution time."""

    require_parameters: bool = False
    response_healing: bool = False


class GenerationRequest(BaseModel):
    """Provider-neutral non-streaming text generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_id: ModelIdentifier
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)
    max_output_tokens: int | None = Field(default=None, ge=1, le=MAX_EXECUTION_OUTPUT_TOKENS)
    structured_output: StructuredOutputRequest | None = None
    json_object: JsonObjectRequest | None = None
    provider_options: ProviderRequestOptions | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if MODEL_ID_PATTERN.fullmatch(self.model_id) is None:
            raise ValueError("model_id contains unsupported characters")
        if self.structured_output is not None and self.json_object is not None:
            raise ValueError("structured_output and json_object are mutually exclusive")
        if sum(len(message.content) for message in self.messages) > MAX_REQUEST_CHARACTERS:
            raise ValueError("message content exceeds the request limit")
        return self


class GenerationResult(BaseModel):
    """Normalized result with no raw provider object attached."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_id: ModelIdentifier
    model_id: ModelIdentifier
    provider_resolved_model_id: ModelIdentifier | None = None
    upstream_provider_id: str | None = Field(default=None, min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=MAX_RESULT_CHARACTERS)
    finish_reason: str | None = Field(default=None, min_length=1, max_length=128)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=128)
    duration_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_identifiers(self) -> Self:
        if PROVIDER_ID_PATTERN.fullmatch(self.provider_id) is None:
            raise ValueError("provider_id contains unsupported characters")
        if MODEL_ID_PATTERN.fullmatch(self.model_id) is None:
            raise ValueError("model_id contains unsupported characters")
        if (
            self.provider_resolved_model_id is not None
            and MODEL_ID_PATTERN.fullmatch(self.provider_resolved_model_id) is None
        ):
            raise ValueError("provider_resolved_model_id contains unsupported characters")
        if (
            self.upstream_provider_id is not None
            and UPSTREAM_PROVIDER_PATTERN.fullmatch(self.upstream_provider_id) is None
        ):
            raise ValueError("upstream_provider_id contains unsupported characters")
        return self
