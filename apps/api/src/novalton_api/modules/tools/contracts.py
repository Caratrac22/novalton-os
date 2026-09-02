"""Closed-world contracts for trusted read-only tools and untrusted proposals."""

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.policy.schemas import RiskLevel

Identifier = str
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*$")


def _identifier(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 100 or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("value must be a normalized identifier")
    return value


def _relative_path(value: str) -> str:
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative to the approved workspace")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError("path traversal is not allowed")
    normalized = path.as_posix()
    if normalized != value and not (value == "." and normalized == "."):
        raise ValueError("path must be normalized")
    return normalized


class ToolContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SideEffectClass(StrEnum):
    READ_ONLY = "READ_ONLY"
    MUTATION = "MUTATION"


class WorkspaceListFilesInput(ToolContract):
    path: str = Field(default=".", min_length=1, max_length=300)
    max_depth: int = Field(default=2, ge=0, le=4)
    max_results: int = Field(default=100, ge=1, le=200)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)


class WorkspaceReadFileInput(ToolContract):
    path: str = Field(min_length=1, max_length=300)
    max_bytes: int = Field(default=32_768, ge=1, le=65_536)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)


class WorkspaceSearchTextInput(ToolContract):
    query: str = Field(min_length=1, max_length=128)
    path: str = Field(default=".", min_length=1, max_length=300)
    max_results: int = Field(default=50, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("query must be bounded printable text")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)


class WorkspaceListFilesArguments(WorkspaceListFilesInput):
    """Closed proposal arguments for workspace.list_files."""


class WorkspaceReadFileArguments(WorkspaceReadFileInput):
    """Closed proposal arguments for workspace.read_file."""


class WorkspaceSearchTextArguments(WorkspaceSearchTextInput):
    """Closed proposal arguments for workspace.search_text."""


class WorkspaceReplaceTextInput(ToolContract):
    path: str = Field(min_length=1, max_length=300)
    search: str = Field(min_length=1, max_length=16_384)
    replacement: str = Field(max_length=16_384)
    expected_matches: int = Field(default=1, ge=1, le=8)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("search", "replacement")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\n\t\r" for character in value):
            raise ValueError("text contains forbidden control characters")
        return value


class WorkspaceReplaceTextArguments(WorkspaceReplaceTextInput):
    """Closed proposal arguments for workspace.replace_text."""


class ToolProposal(ToolContract):
    """A model-authored proposal with a closed, tool-specific argument schema."""

    call_key: Identifier
    tool_name: Literal[
        "workspace.list_files",
        "workspace.read_file",
        "workspace.search_text",
        "workspace.replace_text",
    ]
    arguments: (
        WorkspaceListFilesArguments
        | WorkspaceReadFileArguments
        | WorkspaceSearchTextArguments
        | WorkspaceReplaceTextArguments
    )

    @model_validator(mode="before")
    @classmethod
    def parse_tool_arguments(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        tool_name = value.get("tool_name")
        argument_models = {
            "workspace.list_files": WorkspaceListFilesArguments,
            "workspace.read_file": WorkspaceReadFileArguments,
            "workspace.search_text": WorkspaceSearchTextArguments,
            "workspace.replace_text": WorkspaceReplaceTextArguments,
        }
        model = argument_models.get(tool_name)
        if model is None:
            return value
        parsed = dict(value)
        parsed["arguments"] = model.model_validate(parsed.get("arguments"), strict=True)
        return parsed

    @field_validator("call_key")
    @classmethod
    def normalize_call_key(cls, value: str) -> str:
        return _identifier(value)


class ToolEvidence(ToolContract):
    """Transient bounded evidence; content is never durable audit metadata."""

    tool_name: Identifier
    call_key: Identifier
    data: dict[str, Any]
    authority: Literal["UNTRUSTED_DATA"] = "UNTRUSTED_DATA"


class ToolExecutionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ToolGatewayResult(ToolContract):
    tool_call_id: str
    status: ToolExecutionStatus
    policy_effect: str | None = None
    approval_id: str | None = None
    evidence: ToolEvidence | None = None
    failure_code: str | None = None


class ToolDefinition(ToolContract):
    """Safe public projection of immutable registry metadata."""

    tool_id: Identifier
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, Any]
    output_max_bytes: int = Field(ge=1, le=262_144)
    risk_class: RiskLevel
    execution_locality: ExecutionTargetClass
    required_permission: Identifier
    policy_action: Identifier
    side_effect_class: SideEffectClass
