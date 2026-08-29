"""Authoritative deterministic Memory-to-model disclosure policy."""

from dataclasses import dataclass

from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.memories.schemas import MemoryModelAccess


@dataclass(frozen=True)
class MemoryDisclosureDecision:
    eligible: bool
    reason_code: str | None = None


def evaluate_memory_disclosure(
    *, model_access: MemoryModelAccess, execution_target_class: ExecutionTargetClass
) -> MemoryDisclosureDecision:
    """Apply the record's intrinsic access policy without provider or caller input."""
    if execution_target_class == ExecutionTargetClass.LOCAL:
        return MemoryDisclosureDecision(eligible=True)
    if model_access == MemoryModelAccess.LOCAL_AND_REMOTE:
        return MemoryDisclosureDecision(eligible=True)
    return MemoryDisclosureDecision(eligible=False, reason_code="local_only")
