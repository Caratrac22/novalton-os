"""Strict metadata-only contracts for the Developer Worker Agent."""

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Self

from pydantic import Field, field_validator, model_validator

from novalton_api.modules.agents.contracts import (
    AgentInput,
    AgentResult,
    AgentResultStatus,
    ArtifactReference,
    ContractModel,
    Identifier,
    RequestedAction,
    ShortText,
    _identifier,
    _safe_text,
)
from novalton_api.modules.tools.contracts import ToolProposal

DEVELOPER_WORKER_OUTPUT = "development.implementation_result"
DEVELOPER_WORKER_TOOLS = [
    "workspace.list_files",
    "workspace.read_file",
    "workspace.search_text",
    "workspace.replace_text",
]
MAX_PROPOSED_CHANGES = 32
MAX_ACCEPTANCE_CHECKS = 24
MAX_TEST_RECOMMENDATIONS = 24
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class DevelopmentAssignmentInput(AgentInput):
    """One trusted bounded assignment with no tool or model override authority."""

    expected_output_type: Identifier = DEVELOPER_WORKER_OUTPUT
    permitted_tools: list[Identifier] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_worker_input(self) -> Self:
        if self.expected_output_type != DEVELOPER_WORKER_OUTPUT:
            raise ValueError("expected_output_type must request an implementation result")
        if any(tool not in DEVELOPER_WORKER_TOOLS for tool in self.permitted_tools):
            raise ValueError("Developer Worker permits only trusted workspace tools")
        if self.model_requirements is not None and self.model_requirements.tool_calling_required:
            raise ValueError("provider-native tool calling is not used for trusted tool proposals")
        return self


class ChangeKind(StrEnum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    CONFIG = "CONFIG"
    TEST = "TEST"


class AcceptanceStatus(StrEnum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _relative_path(value: str) -> str:
    value = _safe_text(value).replace("\\", "/")
    path = PurePosixPath(value)
    if (
        value.startswith("/")
        or _WINDOWS_DRIVE.match(value)
        or "://" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.is_absolute()
    ):
        raise ValueError("path must be a normalized relative path")
    normalized = path.as_posix()
    if normalized != value or len(normalized) > 300:
        raise ValueError("path must be a normalized relative path")
    return normalized


class ProposedChange(ContractModel):
    path: str = Field(min_length=1, max_length=300)
    kind: ChangeKind
    rationale: str = Field(min_length=1, max_length=1000)
    expected_effect: str = Field(min_length=1, max_length=1000)
    acceptance_criteria: list[Identifier] = Field(default_factory=list, max_length=12)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("rationale", "expected_effect")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_criteria(cls, values: list[str]) -> list[str]:
        normalized = [_identifier(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate acceptance criterion reference")
        return sorted(normalized)


class AcceptanceCheck(ContractModel):
    criterion_id: Identifier
    status: AcceptanceStatus
    detail: ShortText

    @field_validator("criterion_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("detail")
    @classmethod
    def validate_detail(cls, value: str) -> str:
        return _safe_text(value)


class DeveloperWorkerTerminalResult(AgentResult):
    """Validated terminal implementation result; it cannot propose tools."""

    task_interpretation: str = Field(min_length=1, max_length=2000)
    implementation_summary: str = Field(min_length=1, max_length=3000)
    changes: list[ProposedChange] = Field(max_length=MAX_PROPOSED_CHANGES)
    acceptance_checks: list[AcceptanceCheck] = Field(max_length=MAX_ACCEPTANCE_CHECKS)
    test_recommendations: list[ShortText] = Field(max_length=MAX_TEST_RECOMMENDATIONS)
    blockers: list[ShortText] = Field(max_length=16)
    artifacts: list[ArtifactReference] = Field(default_factory=list, max_length=0)
    requested_actions: list[RequestedAction] = Field(default_factory=list, max_length=0)

    @field_validator("task_interpretation", "implementation_summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("test_recommendations", "blockers")
    @classmethod
    def normalize_text_list(cls, values: list[str]) -> list[str]:
        normalized = [_safe_text(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate entries are not allowed")
        return sorted(normalized)

    @model_validator(mode="after")
    def normalize_result(self) -> Self:
        change_keys = [(change.path, change.kind.value) for change in self.changes]
        if len(change_keys) != len(set(change_keys)):
            raise ValueError("duplicate proposed change descriptor")
        check_ids = [check.criterion_id for check in self.acceptance_checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("duplicate acceptance check")
        return self.model_copy(
            update={
                "changes": sorted(self.changes, key=lambda item: (item.path, item.kind.value)),
                "acceptance_checks": sorted(
                    self.acceptance_checks, key=lambda item: item.criterion_id
                ),
            }
        )


class DeveloperWorkerResult(DeveloperWorkerTerminalResult):
    """Initial Developer result; it may make one bounded tool proposal."""

    tool_proposals: list[ToolProposal] = Field(default_factory=list, max_length=1)

    @model_validator(mode="after")
    def validate_tool_proposal_status(self) -> Self:
        if self.tool_proposals and self.status != AgentResultStatus.PARTIAL:
            raise ValueError("a tool proposal requires PARTIAL status")
        return self
