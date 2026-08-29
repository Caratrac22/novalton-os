"""Unit tests for provider-free bounded Memory context assembly."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from novalton_api.infrastructure.providers.contracts import ExecutionTargetClass
from novalton_api.modules.memories.context_packages import (
    DEFAULT_CONTEXT_PACKAGE_BOUNDS,
    ContextPackageBounds,
    assemble_context_package,
    filter_context_package_for_target,
)
from novalton_api.modules.memories.schemas import (
    KnowledgeState,
    MemoryKind,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
)

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000002")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000011")
TASK_ID = UUID("00000000-0000-0000-0000-000000000021")
RUN_ID = UUID("00000000-0000-0000-0000-000000000031")
AS_OF = datetime(2026, 8, 27, 12, tzinfo=UTC)
ASSEMBLED_AT = datetime(2026, 8, 27, 12, 1, tzinfo=UTC)


def _result(
    index: int,
    *,
    kind: MemoryKind = MemoryKind.FACT,
    knowledge_state: KnowledgeState = KnowledgeState.CONFIRMED_FACT,
    statement: str | None = None,
    workspace_id: UUID = WORKSPACE_ID,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    workflow_run_id: UUID | None = None,
    provenance_count: int = 1,
    lexical_relevance: float | None = None,
    model_access: str = "LOCAL_ONLY",
) -> MemoryRetrievalResult:
    return MemoryRetrievalResult(
        id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        kind=kind,
        knowledge_state=knowledge_state,
        statement=statement or f"memory {index}",
        confidence=0.75,
        importance=3,
        valid_from=AS_OF,
        valid_to=None,
        lifecycle="ACTIVE",
        model_access=model_access,
        created_at=AS_OF,
        updated_at=AS_OF,
        provenance=[
            {
                "id": UUID(f"10000000-0000-0000-0000-{index * 100 + source:012d}"),
                "source_type": "DOCUMENT",
                "source_reference_id": f"source-{index}-{source}",
                "created_at": AS_OF,
            }
            for source in range(provenance_count)
        ],
        lexical_relevance=lexical_relevance,
    )


def _assemble(
    results: list[MemoryRetrievalResult],
    *,
    request: MemoryRetrievalRequest | None = None,
    bounds: ContextPackageBounds = DEFAULT_CONTEXT_PACKAGE_BOUNDS,
):
    return assemble_context_package(
        retrieval_results=results,
        workspace_id=WORKSPACE_ID,
        request=request or MemoryRetrievalRequest(as_of=AS_OF),
        as_of=AS_OF,
        assembled_at=ASSEMBLED_AT,
        bounds=bounds,
    )


def test_fixed_retrieval_input_has_deterministic_semantic_package() -> None:
    results = [
        _result(1, lexical_relevance=0.9),
        _result(2, kind=MemoryKind.DECISION, knowledge_state=KnowledgeState.INFERENCE),
    ]
    first = _assemble(results)
    second = _assemble(results)

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.assembled_at == ASSEMBLED_AT
    assert first.as_of == AS_OF


@pytest.mark.parametrize(
    ("kind", "group"),
    [
        (MemoryKind.FACT, "facts"),
        (MemoryKind.DECISION, "decisions"),
        (MemoryKind.PREFERENCE, "preferences"),
        (MemoryKind.CONSTRAINT, "constraints"),
        (MemoryKind.EVENT, "relevant_events"),
        (MemoryKind.NOTE, "relevant_notes"),
    ],
)
def test_memory_kinds_have_only_supported_context_groups(kind: MemoryKind, group: str) -> None:
    package = _assemble([_result(1, kind=kind)])

    assert [item.memory_id for item in getattr(package, group)] == [_result(1, kind=kind).id]
    assert package.included_count == 1


def test_epistemic_states_remain_visible_and_disputed_is_separate() -> None:
    inference = _result(1, knowledge_state=KnowledgeState.INFERENCE)
    hypothesis = _result(2, knowledge_state=KnowledgeState.HYPOTHESIS)
    disputed = _result(3, knowledge_state=KnowledgeState.DISPUTED)
    package = _assemble([inference, hypothesis, disputed])

    assert [item.knowledge_state for item in package.facts] == [
        KnowledgeState.INFERENCE,
        KnowledgeState.HYPOTHESIS,
    ]
    assert [item.memory_id for item in package.disputed] == [disputed.id]
    assert disputed.id not in [item.memory_id for item in package.facts]


def test_builder_preserves_supplied_archived_and_obsolete_results_without_resurrecting() -> None:
    historical = _result(1, knowledge_state=KnowledgeState.OBSOLETE)
    archived = _result(2)
    archived = archived.model_copy(update={"lifecycle": "ARCHIVED"})
    package = _assemble([historical, archived])

    assert [item.knowledge_state for item in package.facts] == [
        KnowledgeState.OBSOLETE,
        KnowledgeState.CONFIRMED_FACT,
    ]
    assert [item.lifecycle.value for item in package.facts] == ["ACTIVE", "ARCHIVED"]


def test_provenance_and_memory_ids_are_retained_without_raw_source_payload() -> None:
    result = _result(1, provenance_count=2, lexical_relevance=0.5)
    item = _assemble([result]).facts[0]

    assert item.memory_id == result.id
    assert [(entry.source_type, entry.source_reference_id) for entry in item.provenance] == [
        ("DOCUMENT", "source-1-0"),
        ("DOCUMENT", "source-1-1"),
    ]
    assert item.lexical_relevance == 0.5
    assert "raw_source" not in item.model_dump()


def test_hard_item_bound_and_omission_follow_retrieval_order() -> None:
    results = [_result(index) for index in range(1, 5)]
    package = _assemble(results, bounds=ContextPackageBounds(max_items=2))

    assert [item.memory_id for item in package.facts] == [results[0].id, results[1].id]
    assert package.included_count == 2
    assert package.omitted_count == 2


def test_byte_bound_drops_whole_later_statement_without_truncating() -> None:
    first = _result(1, statement="first")
    second_statement = "second-" * 200
    second = _result(2, statement=second_statement)
    bounds = ContextPackageBounds(max_serialized_bytes=1_024)
    package = _assemble([first, second], bounds=bounds)

    assert [item.statement for item in package.facts] == ["first"]
    assert package.omitted_count == 1
    assert package.serialized_bytes <= bounds.max_serialized_bytes
    assert second_statement not in [item.statement for item in package.facts]


def test_provenance_has_explicit_per_item_and_package_bounds() -> None:
    first = _result(1, provenance_count=4)
    second = _result(2, provenance_count=4)
    package = _assemble(
        [first, second],
        bounds=ContextPackageBounds(max_provenance_per_item=3, max_provenance_references=4),
    )

    assert [len(item.provenance) for item in package.facts] == [3, 1]
    assert [item.provenance_omitted_count for item in package.facts] == [1, 3]
    assert package.provenance_omitted_count == 4


def test_scope_mismatch_is_rejected_before_any_package_can_be_assembled() -> None:
    with pytest.raises(ValueError, match="workspace"):
        _assemble([_result(1, workspace_id=OTHER_WORKSPACE_ID)])
    request = MemoryRetrievalRequest(project_id=PROJECT_ID, task_id=TASK_ID, workflow_run_id=RUN_ID)
    with pytest.raises(ValueError, match="scope"):
        _assemble([_result(1)], request=request)


def test_project_task_and_workflow_scope_is_preserved() -> None:
    request = MemoryRetrievalRequest(project_id=PROJECT_ID, task_id=TASK_ID, workflow_run_id=RUN_ID)
    package = _assemble(
        [_result(1, project_id=PROJECT_ID, task_id=TASK_ID, workflow_run_id=RUN_ID)],
        request=request,
    )

    assert (package.workspace_id, package.project_id, package.task_id, package.workflow_run_id) == (
        WORKSPACE_ID,
        PROJECT_ID,
        TASK_ID,
        RUN_ID,
    )


def test_empty_retrieval_is_a_valid_provider_free_package() -> None:
    package = _assemble([])

    assert package.included_count == package.omitted_count == 0
    assert package.facts == package.disputed == ()
    assert package.serialized_bytes <= package.bounds.max_serialized_bytes


def test_target_filter_removes_denied_content_without_changing_eligible_order_or_bounds() -> None:
    local_only = _result(1, statement="local secret", model_access="LOCAL_ONLY")
    remote_eligible = _result(2, statement="remote safe", model_access="LOCAL_AND_REMOTE")
    package = _assemble([local_only, remote_eligible])

    filtered = filter_context_package_for_target(
        package, execution_target_class=ExecutionTargetClass.REMOTE
    )

    assert [item.memory_id for item in filtered.facts] == [remote_eligible.id]
    assert filtered.policy_omitted_count == 1
    assert filtered.included_count == 1
    assert filtered.omitted_count == 1
    assert filtered.serialized_bytes <= filtered.bounds.max_serialized_bytes
    assert "local secret" not in filtered.model_dump_json()
