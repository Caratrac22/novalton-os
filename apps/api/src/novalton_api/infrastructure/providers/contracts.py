"""Strict provider-neutral text generation contracts."""

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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

ModelIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]


class CatalogModel(BaseModel):
    """One provider-normalized catalog entry with no raw metadata attached."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_model_id: ModelIdentifier
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)
    reasoning: bool | None = None
    coding: bool | None = None
    tool_calling: bool | None = None
    structured_output: bool | None = None
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
        return self


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


class GenerationRequest(BaseModel):
    """Provider-neutral non-streaming text generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_id: ModelIdentifier
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)
    max_output_tokens: int | None = Field(default=None, ge=1, le=65_536)
    structured_output: StructuredOutputRequest | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if MODEL_ID_PATTERN.fullmatch(self.model_id) is None:
            raise ValueError("model_id contains unsupported characters")
        if sum(len(message.content) for message in self.messages) > MAX_REQUEST_CHARACTERS:
            raise ValueError("message content exceeds the request limit")
        return self


class GenerationResult(BaseModel):
    """Normalized result with no raw provider object attached."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_id: ModelIdentifier
    model_id: ModelIdentifier
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
        return self
