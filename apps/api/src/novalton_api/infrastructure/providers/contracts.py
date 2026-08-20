"""Strict provider-neutral text generation contracts."""

import re
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_MESSAGES = 128
MAX_MESSAGE_CHARACTERS = 65_536
MAX_REQUEST_CHARACTERS = 262_144
MAX_RESULT_CHARACTERS = 1_048_576
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")

ModelIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
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


class GenerationRequest(BaseModel):
    """Provider-neutral non-streaming text generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_id: ModelIdentifier
    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)
    max_output_tokens: int | None = Field(default=None, ge=1, le=65_536)

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
        if MODEL_ID_PATTERN.fullmatch(self.provider_id) is None:
            raise ValueError("provider_id contains unsupported characters")
        if MODEL_ID_PATTERN.fullmatch(self.model_id) is None:
            raise ValueError("model_id contains unsupported characters")
        return self
