"""Provider-neutral output-budget policy for agent generations."""

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class OutputBudget:
    tokens: int
    known_model_maximum: int | None
    source: str


def classify_truncation(finish_reason: str | None) -> str:
    """Classify only explicit provider token-limit reasons as truncation."""
    if finish_reason is None:
        return "NONE"
    normalized = finish_reason.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"length", "max_tokens", "max_output_tokens", "token_limit", "token_length"}:
        return "TOKEN_LIMIT"
    return "OTHER"


def select_output_budget(
    *,
    expected_output_tokens: int,
    known_model_maximum: int | None,
    safety_ceiling: int,
    recovery: bool = False,
) -> OutputBudget:
    """Choose a bounded budget, expanding once for an explicitly truncated result."""
    target = max(expected_output_tokens, ceil(expected_output_tokens * 1.5))
    ceiling = min(known_model_maximum, safety_ceiling) if known_model_maximum else safety_ceiling
    if recovery:
        target = max(target, ceil(target * 1.5))
    selected = min(target, ceiling)
    source = "model_maximum" if known_model_maximum is not None else "configured_safety_ceiling"
    if recovery:
        source = f"recovery_{source}"
    return OutputBudget(
        tokens=max(1, selected), known_model_maximum=known_model_maximum, source=source
    )
