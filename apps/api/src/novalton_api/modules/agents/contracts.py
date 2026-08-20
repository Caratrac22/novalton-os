"""Strict provider-neutral contracts for future agent execution.

Validation in this module is pure: it grants no authority, performs no I/O, and
does not mutate the Agent Run lifecycle or persistence state.
"""

import re
from enum import StrEnum
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from novalton_api.modules.policy.schemas import RiskLevel

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*$")
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CONTENT_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$")
_CREDENTIAL = re.compile(
    r"(?:authorization\s*:|api[-_ ]?key\s*[:=]|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
_EMBEDDED_DATA = re.compile(r"(?:^data:|;base64,|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY)", re.I)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ReferenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


def _safe_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must not be blank")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("control characters are not allowed")
    if _CREDENTIAL.search(value):
        raise ValueError("credential material is not allowed")
    return value


def _identifier(value: str) -> str:
    value = value.strip().lower()
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("value must be a normalized identifier")
    return value


def _reference(value: str) -> str:
    value = _safe_text(value)
    if "://" in value or _REFERENCE.fullmatch(value) is None:
        raise ValueError("value must be a bounded reference identifier")
    return value


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted(set(values))


class ContractModel(BaseModel):
    """Common closed-world behavior for untrusted contract data."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ContextReference(ContractModel):
    """Metadata-only pointer to context prepared by a trusted runtime."""

    reference_id: ReferenceId
    label: ShortText | None = None

    @field_validator("reference_id")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return _reference(value)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return _safe_text(value) if value is not None else None


class ModelRequirementHints(ContractModel):
    """Advisory capabilities for the Router; never a model-selection override."""

    required_capabilities: list[Identifier] = Field(default_factory=list, max_length=16)
    minimum_context_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    structured_output_required: bool = True
    tool_calling_required: bool = False

    @field_validator("required_capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_identifier(value) for value in values])


class AgentInput(ContractModel):
    """Bounded input for a future Agent Run, containing no execution authority."""

    objective: str = Field(min_length=1, max_length=4000)
    constraints: list[ShortText] = Field(default_factory=list, max_length=32)
    project_id: ReferenceId | None = None
    task_id: ReferenceId | None = None
    context_references: list[ContextReference] = Field(default_factory=list, max_length=32)
    source_references: list[ReferenceId] = Field(default_factory=list, max_length=32)
    prior_result_references: list[ReferenceId] = Field(default_factory=list, max_length=16)
    expected_output_type: Identifier
    permitted_tools: list[Identifier] = Field(default_factory=list, max_length=32)
    model_requirements: ModelRequirementHints | None = None

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("constraints")
    @classmethod
    def normalize_constraints(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_safe_text(value) for value in values])

    @field_validator("project_id", "task_id")
    @classmethod
    def validate_optional_reference(cls, value: str | None) -> str | None:
        return _reference(value) if value is not None else None

    @field_validator("source_references", "prior_result_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_reference(value) for value in values])

    @field_validator("expected_output_type")
    @classmethod
    def validate_expected_output(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("permitted_tools")
    @classmethod
    def normalize_tools(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_identifier(value) for value in values])

    @model_validator(mode="after")
    def validate_task_scope(self) -> Self:
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task_id requires project_id")
        return self


class AgentResultStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    NEEDS_INPUT = "NEEDS_INPUT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Finding(ContractModel):
    category: Identifier
    title: str = Field(min_length=1, max_length=300)
    detail: str = Field(min_length=1, max_length=4000)
    severity: FindingSeverity | None = None
    source_references: list[ReferenceId] = Field(default_factory=list, max_length=16)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title", "detail")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("source_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_reference(value) for value in values])


class SourceReference(ContractModel):
    source_id: ReferenceId
    label: str = Field(min_length=1, max_length=300)
    source_type: Identifier | None = None
    provenance_uri: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _reference(value)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, value: str | None) -> str | None:
        return _identifier(value) if value is not None else None

    @field_validator("provenance_uri")
    @classmethod
    def validate_provenance_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _safe_text(value)
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("provenance_uri must be an absolute HTTP(S) metadata URI")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("provenance_uri must not contain credentials, query, or fragment")
        return value


class ArtifactReference(ContractModel):
    artifact_id: ReferenceId
    artifact_type: Identifier
    label: str = Field(min_length=1, max_length=300)
    path: str | None = Field(default=None, min_length=1, max_length=512)
    external_reference: ReferenceId | None = None
    content_type: str | None = Field(default=None, min_length=3, max_length=129)

    @field_validator("artifact_id", "external_reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        return _reference(value) if value is not None else None

    @field_validator("artifact_type")
    @classmethod
    def validate_artifact_type(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _safe_text(value)
        compact = value.replace("\n", "").replace("\r", "")
        looks_like_base64 = len(compact) >= 80 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact)
        if _EMBEDDED_DATA.search(value) or looks_like_base64:
            raise ValueError("embedded artifact content is not allowed")
        return value

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, value: str | None) -> str | None:
        if value is not None and _CONTENT_TYPE.fullmatch(value) is None:
            raise ValueError("content_type must be a normalized media type")
        return value


class Assumption(ContractModel):
    statement: str = Field(min_length=1, max_length=1000)
    source_references: list[ReferenceId] = Field(default_factory=list, max_length=8)

    @field_validator("statement")
    @classmethod
    def validate_statement(cls, value: str) -> str:
        return _safe_text(value)

    @field_validator("source_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_reference(value) for value in values])


class Risk(Assumption):
    severity: RiskLevel


class Uncertainty(Assumption):
    pass


class BlockingIssue(Assumption):
    pass


class ChallengeLevel(StrEnum):
    NONE = "NONE"
    WARNING = "WARNING"
    HUMAN_REVIEW_RECOMMENDED = "HUMAN_REVIEW_RECOMMENDED"
    BLOCK_RECOMMENDED = "BLOCK_RECOMMENDED"


class Challenge(ContractModel):
    level: ChallengeLevel
    reason: str | None = Field(default=None, min_length=1, max_length=2000)
    evidence_source_references: list[ReferenceId] = Field(default_factory=list, max_length=16)
    suggested_action: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("reason", "suggested_action")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _safe_text(value) if value is not None else None

    @field_validator("evidence_source_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        return _unique_sorted([_reference(value) for value in values])

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if self.level == ChallengeLevel.NONE:
            if self.reason is not None or self.evidence_source_references or self.suggested_action:
                raise ValueError("NONE challenge cannot contain challenge metadata")
        elif self.reason is None:
            raise ValueError("a meaningful challenge requires a reason")
        return self


class RequestedAction(ContractModel):
    """An advisory proposal only; this contract cannot approve or execute it."""

    action_type: Identifier
    target_reference: ReferenceId
    reason: str = Field(min_length=1, max_length=1000)
    risk_hint: RiskLevel | None = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str) -> str:
        value = _identifier(value)
        if "." not in value:
            raise ValueError("action_type must be a dot-separated identifier")
        return value

    @field_validator("target_reference")
    @classmethod
    def validate_target(cls, value: str) -> str:
        return _reference(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _safe_text(value)


class RecommendedNextStep(ContractModel):
    recommendation: str = Field(min_length=1, max_length=1000)

    @field_validator("recommendation")
    @classmethod
    def validate_recommendation(cls, value: str) -> str:
        return _safe_text(value)


class AgentResult(ContractModel):
    """Operational result data distinct from the persisted Agent Run status."""

    status: AgentResultStatus
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[Finding] = Field(max_length=64)
    artifacts: list[ArtifactReference] = Field(max_length=32)
    sources: list[SourceReference] = Field(max_length=64)
    assumptions: list[Assumption] = Field(max_length=32)
    risks: list[Risk] = Field(max_length=32)
    uncertainties: list[Uncertainty] = Field(max_length=32)
    blocking_issues: list[BlockingIssue] = Field(max_length=32)
    challenge: Challenge
    recommended_next_steps: list[RecommendedNextStep] = Field(max_length=32)
    requested_actions: list[RequestedAction] = Field(max_length=32)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _safe_text(value)
