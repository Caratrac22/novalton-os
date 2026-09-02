"""Strict metadata-only contracts for the QA Worker Agent."""

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from novalton_api.modules.agents.contracts import (
    AgentInput,
    AgentResult,
    AgentResultStatus,
    ArtifactReference,
    ChallengeLevel,
    ContractModel,
    Identifier,
    RequestedAction,
    ShortText,
    _identifier,
    _reference,
    _safe_text,
)

QA_ASSESSMENT_OUTPUT = "quality.qa_assessment"
MAX_VALIDATION_CRITERIA = 24
MAX_ACCEPTANCE_RESULTS = 24
MAX_DEFECTS = 32
MAX_RECOMMENDATIONS = 24
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_UNSAFE_TEXT = re.compile(
    r"(?:https?://|data:|;base64,|```|\$\(|&&|\|\||\b(?:sudo|curl|wget)\s)", re.IGNORECASE
)


def _bounded_qa_text(value: str) -> str:
    value = _safe_text(value)
    if _UNSAFE_TEXT.search(value):
        raise ValueError("executable or externally addressed content is not allowed")
    return value


def _relative_path(value: str) -> str:
    value = _bounded_qa_text(value).replace("\\", "/")
    path = PurePosixPath(value)
    if (
        value.startswith("/")
        or _WINDOWS_DRIVE.match(value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.is_absolute()
    ):
        raise ValueError("path must be a normalized relative path")
    normalized = path.as_posix()
    if normalized != value or len(normalized) > 300:
        raise ValueError("path must be a normalized relative path")
    return normalized


def _reject_unsafe_content(value: object) -> None:
    if isinstance(value, str) and _UNSAFE_TEXT.search(value):
        raise ValueError("executable or externally addressed content is not allowed")
    if isinstance(value, dict):
        for nested in value.values():
            _reject_unsafe_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_unsafe_content(nested)


class ValidationCriterion(ContractModel):
    criterion_id: Identifier
    description: str = Field(min_length=1, max_length=1000)
    evidence_references: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("criterion_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _bounded_qa_text(value)

    @field_validator("evidence_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        normalized = [_reference(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate evidence reference")
        return sorted(normalized)


class QAValidationInput(AgentInput):
    """One explicit trusted validation assignment with no execution authority."""

    expected_output_type: Identifier = QA_ASSESSMENT_OUTPUT
    permitted_tools: list[Identifier] = Field(default_factory=list, max_length=0)
    acceptance_criteria: list[ValidationCriterion] = Field(
        min_length=1, max_length=MAX_VALIDATION_CRITERIA
    )

    @field_validator("acceptance_criteria")
    @classmethod
    def normalize_criteria(cls, values: list[ValidationCriterion]) -> list[ValidationCriterion]:
        criterion_ids = [criterion.criterion_id for criterion in values]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("duplicate validation criterion")
        return sorted(values, key=lambda criterion: criterion.criterion_id)

    @model_validator(mode="after")
    def validate_qa_input(self) -> Self:
        if self.expected_output_type != QA_ASSESSMENT_OUTPUT:
            raise ValueError("expected_output_type must request a QA assessment")
        if self.model_requirements is not None and self.model_requirements.tool_calling_required:
            raise ValueError("QA Worker execution cannot require tool calling")
        return self


class QAVerdict(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class AcceptanceResultStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"


class DefectSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AcceptanceResult(ContractModel):
    criterion_id: Identifier
    status: AcceptanceResultStatus
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_references: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("criterion_id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str) -> str:
        return _bounded_qa_text(value)

    @field_validator("evidence_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        normalized = [_reference(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate evidence reference")
        return sorted(normalized)


class DefectDescriptor(ContractModel):
    defect_key: Identifier
    title: str = Field(min_length=1, max_length=300)
    severity: DefectSeverity
    component_path: str | None = Field(default=None, min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=2000)
    affected_criteria: list[Identifier] = Field(default_factory=list, max_length=12)
    remediation_summary: str = Field(min_length=1, max_length=1000)

    @field_validator("defect_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("title", "description", "remediation_summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _bounded_qa_text(value)

    @field_validator("component_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        return _relative_path(value) if value is not None else None

    @field_validator("affected_criteria")
    @classmethod
    def normalize_criteria(cls, values: list[str]) -> list[str]:
        normalized = [_identifier(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate affected criterion")
        return sorted(normalized)


class QAWorkerResult(AgentResult):
    """A bounded QA assessment, not approval or executable validation."""

    validation_summary: str = Field(min_length=1, max_length=3000)
    verdict: QAVerdict
    acceptance_results: list[AcceptanceResult] = Field(
        min_length=1, max_length=MAX_ACCEPTANCE_RESULTS
    )
    defects: list[DefectDescriptor] = Field(max_length=MAX_DEFECTS)
    test_recommendations: list[ShortText] = Field(max_length=MAX_RECOMMENDATIONS)
    regression_risks: list[ShortText] = Field(max_length=MAX_RECOMMENDATIONS)
    security_review_recommendations: list[ShortText] = Field(max_length=MAX_RECOMMENDATIONS)
    manual_review_recommendations: list[ShortText] = Field(max_length=MAX_RECOMMENDATIONS)
    blockers: list[ShortText] = Field(max_length=16)
    artifacts: list[ArtifactReference] = Field(default_factory=list, max_length=0)
    requested_actions: list[RequestedAction] = Field(default_factory=list, max_length=0)

    @field_validator("validation_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _bounded_qa_text(value)

    @field_validator(
        "test_recommendations",
        "regression_risks",
        "security_review_recommendations",
        "manual_review_recommendations",
        "blockers",
    )
    @classmethod
    def normalize_text_list(cls, values: list[str]) -> list[str]:
        normalized = [_bounded_qa_text(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate entries are not allowed")
        return sorted(normalized)

    @model_validator(mode="after")
    def normalize_and_validate_result(self) -> Self:
        _reject_unsafe_content(self.model_dump(mode="json"))
        criterion_ids = [item.criterion_id for item in self.acceptance_results]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("duplicate acceptance result")
        defect_keys = [defect.defect_key for defect in self.defects]
        if len(defect_keys) != len(set(defect_keys)):
            raise ValueError("duplicate defect key")
        unknown_criteria = {
            criterion
            for defect in self.defects
            for criterion in defect.affected_criteria
            if criterion not in set(criterion_ids)
        }
        if unknown_criteria:
            raise ValueError("defect references an unknown acceptance criterion")
        statuses = {item.status for item in self.acceptance_results}
        if self.verdict == QAVerdict.PASS:
            if (
                self.status != AgentResultStatus.COMPLETED
                or statuses - {AcceptanceResultStatus.PASS}
                or self.defects
                or self.blockers
                or self.challenge.level != ChallengeLevel.NONE
            ):
                raise ValueError("PASS verdict requires complete unchallenged passing evidence")
        elif self.verdict == QAVerdict.FAIL and AcceptanceResultStatus.FAIL not in statuses:
            raise ValueError("FAIL verdict requires a failed acceptance result")
        elif self.verdict == QAVerdict.INCONCLUSIVE and not (
            AcceptanceResultStatus.NOT_VERIFIED in statuses
            or self.blockers
            or self.challenge.level != ChallengeLevel.NONE
        ):
            raise ValueError("INCONCLUSIVE verdict requires unresolved evidence")
        return self.model_copy(
            update={
                "acceptance_results": sorted(
                    self.acceptance_results, key=lambda item: item.criterion_id
                ),
                "defects": sorted(self.defects, key=lambda item: item.defect_key),
            }
        )


class QAHumanReviewWarning(ContractModel):
    """One allow-listed warning derived from validated QA-only fields."""

    category: Literal["REGRESSION_RISK", "BLOCKER"]
    message: ShortText

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _bounded_qa_text(value)


class QAHumanReviewRecommendation(ContractModel):
    """One categorized recommendation derived from validated QA-only fields."""

    category: Literal["TEST", "SECURITY_REVIEW", "MANUAL_REVIEW"]
    message: ShortText

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        return _bounded_qa_text(value)


class QAHumanReviewSummary(ContractModel):
    """Bounded durable projection of an already validated structured QA result."""

    schema_version: Literal[1] = 1
    verdict: QAVerdict
    challenge_level: Literal["HUMAN_REVIEW_RECOMMENDED", "BLOCK_RECOMMENDED"]
    challenge_reason: str = Field(min_length=1, max_length=2000)
    challenge_evidence_references: list[str] = Field(default_factory=list, max_length=16)
    suggested_action: ShortText | None = None
    validation_summary: str = Field(min_length=1, max_length=3000)
    warnings: list[QAHumanReviewWarning] = Field(max_length=40)
    recommendations: list[QAHumanReviewRecommendation] = Field(max_length=72)
    acceptance_results: list[AcceptanceResult] = Field(
        min_length=1, max_length=MAX_ACCEPTANCE_RESULTS
    )
    concerns: list[DefectDescriptor] = Field(max_length=MAX_DEFECTS)

    @field_validator("challenge_reason", "validation_summary")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _bounded_qa_text(value)

    @field_validator("suggested_action")
    @classmethod
    def validate_suggested_action(cls, value: str | None) -> str | None:
        return _bounded_qa_text(value) if value is not None else None

    @field_validator("challenge_evidence_references")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        normalized = [_reference(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate challenge evidence reference")
        return sorted(normalized)

    @model_validator(mode="after")
    def validate_safe_summary(self) -> Self:
        _reject_unsafe_content(self.model_dump(mode="json"))
        return self


def human_review_summary(result: QAWorkerResult) -> QAHumanReviewSummary:
    """Select safe QA fields only; generic result/provider content is never copied."""
    if result.challenge.level not in {
        ChallengeLevel.HUMAN_REVIEW_RECOMMENDED,
        ChallengeLevel.BLOCK_RECOMMENDED,
    }:
        raise ValueError("human review summary requires a meaningful QA challenge")
    assert result.challenge.reason is not None
    warnings = [
        QAHumanReviewWarning(category="REGRESSION_RISK", message=value)
        for value in result.regression_risks
    ] + [QAHumanReviewWarning(category="BLOCKER", message=value) for value in result.blockers]
    recommendations = (
        [
            QAHumanReviewRecommendation(category="TEST", message=value)
            for value in result.test_recommendations
        ]
        + [
            QAHumanReviewRecommendation(category="SECURITY_REVIEW", message=value)
            for value in result.security_review_recommendations
        ]
        + [
            QAHumanReviewRecommendation(category="MANUAL_REVIEW", message=value)
            for value in result.manual_review_recommendations
        ]
    )
    return QAHumanReviewSummary(
        verdict=result.verdict,
        challenge_level=result.challenge.level.value,
        challenge_reason=result.challenge.reason,
        challenge_evidence_references=result.challenge.evidence_source_references,
        suggested_action=result.challenge.suggested_action,
        validation_summary=result.validation_summary,
        warnings=warnings,
        recommendations=recommendations,
        acceptance_results=result.acceptance_results,
        concerns=result.defects,
    )
