from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.memories.disclosure import evaluate_memory_disclosure
from novalton_api.modules.memories.schemas import MemoryModelAccess


def test_local_target_can_disclose_local_only_memory() -> None:
    assert evaluate_memory_disclosure(
        model_access=MemoryModelAccess.LOCAL_ONLY,
        execution_target_class=ExecutionTargetClass.LOCAL,
    ).eligible


def test_remote_target_cannot_disclose_local_only_memory() -> None:
    decision = evaluate_memory_disclosure(
        model_access=MemoryModelAccess.LOCAL_ONLY,
        execution_target_class=ExecutionTargetClass.REMOTE,
    )
    assert not decision.eligible
    assert decision.reason_code == "local_only"


def test_remote_target_can_disclose_explicitly_remote_eligible_memory() -> None:
    assert evaluate_memory_disclosure(
        model_access=MemoryModelAccess.LOCAL_AND_REMOTE,
        execution_target_class=ExecutionTargetClass.REMOTE,
    ).eligible
