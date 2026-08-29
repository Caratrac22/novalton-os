"""Deterministic, bounded assembly of trusted Memory retrieval results.

Packages are ephemeral internal contracts.  They deliberately contain only
canonical Memory statements and safe provenance references, never source
payloads or model/provider data.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.memories.schemas import (
    KnowledgeState,
    MemoryKind,
    MemoryLifecycle,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
)

logger = logging.getLogger(__name__)


class ContextPackageBounds(BaseModel):
    """Hard structural limits, intentionally independent of model tokenizers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_items: int = Field(default=12, ge=1, le=50)
    max_serialized_bytes: int = Field(default=16_384, ge=1_024, le=262_144)
    max_provenance_per_item: int = Field(default=4, ge=1, le=16)
    max_provenance_references: int = Field(default=32, ge=1, le=800)


DEFAULT_CONTEXT_PACKAGE_BOUNDS = ContextPackageBounds()


class ContextPackageProvenance(BaseModel):
    """Safe, bounded provenance metadata copied from a Memory retrieval result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    source_type: str
    source_reference_id: str | None
    created_at: datetime


class ContextPackageItem(BaseModel):
    """A canonical Memory statement with explicit epistemic and source metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: UUID
    statement: str
    kind: MemoryKind
    knowledge_state: KnowledgeState
    lifecycle: MemoryLifecycle
    confidence: float
    importance: int
    valid_from: datetime
    valid_to: datetime | None
    provenance: tuple[ContextPackageProvenance, ...]
    provenance_omitted_count: int = Field(ge=0)
    lexical_relevance: float | None = None


class ContextPackage(BaseModel):
    """Provider-neutral, ephemeral working context assembled from retrieval output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    project_id: UUID | None
    task_id: UUID | None
    workflow_run_id: UUID | None
    assembled_at: datetime
    as_of: datetime
    facts: tuple[ContextPackageItem, ...] = ()
    decisions: tuple[ContextPackageItem, ...] = ()
    preferences: tuple[ContextPackageItem, ...] = ()
    constraints: tuple[ContextPackageItem, ...] = ()
    relevant_events: tuple[ContextPackageItem, ...] = ()
    relevant_notes: tuple[ContextPackageItem, ...] = ()
    disputed: tuple[ContextPackageItem, ...] = ()
    included_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)
    provenance_omitted_count: int = Field(ge=0)
    serialized_bytes: int = Field(ge=0)
    bounds: ContextPackageBounds

    @model_validator(mode="after")
    def validate_scope(self) -> ContextPackage:
        if self.task_id is not None and self.project_id is None:
            raise ValueError("task_id requires project_id")
        return self


_GROUP_BY_KIND = {
    MemoryKind.FACT: "facts",
    MemoryKind.DECISION: "decisions",
    MemoryKind.PREFERENCE: "preferences",
    MemoryKind.CONSTRAINT: "constraints",
    MemoryKind.EVENT: "relevant_events",
    MemoryKind.NOTE: "relevant_notes",
}
_GROUP_NAMES = (*_GROUP_BY_KIND.values(), "disputed")


def _serialized_bytes(package: ContextPackage) -> int:
    """Return the complete JSON contract size, including its diagnostic metadata."""
    size = package.serialized_bytes
    for _ in range(4):
        candidate = package.model_copy(update={"serialized_bytes": size})
        next_size = len(candidate.model_dump_json().encode("utf-8"))
        if next_size == size:
            return size
        size = next_size
    raise RuntimeError("context package serialized size did not converge")


def _package(
    *,
    workspace_id: UUID,
    request: MemoryRetrievalRequest,
    as_of: datetime,
    assembled_at: datetime,
    groups: dict[str, list[ContextPackageItem]],
    total_results: int,
    provenance_omitted_count: int,
    bounds: ContextPackageBounds,
) -> ContextPackage:
    included_count = sum(len(group) for group in groups.values())
    return ContextPackage(
        workspace_id=workspace_id,
        project_id=request.project_id,
        task_id=request.task_id,
        workflow_run_id=request.workflow_run_id,
        assembled_at=assembled_at,
        as_of=as_of,
        **{name: tuple(groups[name]) for name in _GROUP_NAMES},
        included_count=included_count,
        omitted_count=total_results - included_count,
        provenance_omitted_count=provenance_omitted_count,
        serialized_bytes=0,
        bounds=bounds,
    )


def _item(
    result: MemoryRetrievalResult,
    *,
    remaining_provenance: int,
    bounds: ContextPackageBounds,
) -> ContextPackageItem:
    provenance_limit = min(bounds.max_provenance_per_item, remaining_provenance)
    retained = tuple(
        ContextPackageProvenance.model_validate(provenance, from_attributes=True)
        for provenance in result.provenance[:provenance_limit]
    )
    return ContextPackageItem(
        memory_id=result.id,
        statement=result.statement,
        kind=result.kind,
        knowledge_state=result.knowledge_state,
        lifecycle=result.lifecycle,
        confidence=result.confidence,
        importance=result.importance,
        valid_from=result.valid_from,
        valid_to=result.valid_to,
        provenance=retained,
        provenance_omitted_count=len(result.provenance) - len(retained),
        lexical_relevance=result.lexical_relevance,
    )


def _validate_result_scope(
    result: MemoryRetrievalResult, *, workspace_id: UUID, request: MemoryRetrievalRequest
) -> None:
    if result.workspace_id != workspace_id:
        raise ValueError("retrieval results must belong to the requested workspace")
    for result_value, requested_value in (
        (result.project_id, request.project_id),
        (result.task_id, request.task_id),
        (result.workflow_run_id, request.workflow_run_id),
    ):
        if requested_value is not None and result_value != requested_value:
            raise ValueError("retrieval result does not satisfy the requested scope")


def assemble_context_package(
    *,
    retrieval_results: Sequence[MemoryRetrievalResult],
    workspace_id: UUID,
    request: MemoryRetrievalRequest,
    as_of: datetime,
    assembled_at: datetime,
    bounds: ContextPackageBounds = DEFAULT_CONTEXT_PACKAGE_BOUNDS,
) -> ContextPackage:
    """Purely assemble retrieval output in retrieval order, dropping whole later items.

    The caller owns retrieval.  This function never queries storage, reranks,
    filters lifecycle/temporal state, summarizes, or calls a provider.
    """
    groups = {name: [] for name in _GROUP_NAMES}
    retained_provenance = 0
    omitted_provenance = 0
    total_results = len(retrieval_results)

    for result in retrieval_results:
        _validate_result_scope(result, workspace_id=workspace_id, request=request)

    for result in retrieval_results:
        if sum(len(group) for group in groups.values()) >= bounds.max_items:
            continue
        candidate_item = _item(
            result,
            remaining_provenance=bounds.max_provenance_references - retained_provenance,
            bounds=bounds,
        )
        group = (
            "disputed"
            if result.knowledge_state == KnowledgeState.DISPUTED
            else _GROUP_BY_KIND[result.kind]
        )
        groups[group].append(candidate_item)
        candidate = _package(
            workspace_id=workspace_id,
            request=request,
            as_of=as_of,
            assembled_at=assembled_at,
            groups=groups,
            total_results=total_results,
            provenance_omitted_count=omitted_provenance + candidate_item.provenance_omitted_count,
            bounds=bounds,
        )
        if _serialized_bytes(candidate) > bounds.max_serialized_bytes:
            groups[group].pop()
            continue
        retained_provenance += len(candidate_item.provenance)
        omitted_provenance += candidate_item.provenance_omitted_count

    package = _package(
        workspace_id=workspace_id,
        request=request,
        as_of=as_of,
        assembled_at=assembled_at,
        groups=groups,
        total_results=total_results,
        provenance_omitted_count=omitted_provenance,
        bounds=bounds,
    )
    serialized_bytes = _serialized_bytes(package)
    if serialized_bytes > bounds.max_serialized_bytes:
        raise RuntimeError("context package bounds cannot encode package metadata")
    return package.model_copy(update={"serialized_bytes": serialized_bytes})


async def retrieve_context_package(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    request: MemoryRetrievalRequest,
    assembled_at: datetime | None = None,
    bounds: ContextPackageBounds = DEFAULT_CONTEXT_PACKAGE_BOUNDS,
) -> ContextPackage:
    """Retrieve under I-032 semantics and immediately assemble an ephemeral package."""
    from novalton_api.modules.memories.service import retrieve_memories

    captured_assembled_at = assembled_at or datetime.now(UTC)
    results, as_of = await retrieve_memories(
        session, tenant_id=tenant_id, workspace_id=workspace_id, data=request
    )
    package = assemble_context_package(
        retrieval_results=[MemoryRetrievalResult.model_validate(result) for result in results],
        workspace_id=workspace_id,
        request=request,
        as_of=as_of,
        assembled_at=captured_assembled_at,
        bounds=bounds,
    )
    logger.info(
        "Memory context package assembled",
        extra={
            "event": "memory.context_package_assembled",
            "workspace_id": str(workspace_id),
            "retrieved_count": len(results),
            "included_count": package.included_count,
            "omitted_count": package.omitted_count,
            "group_counts": {name: len(getattr(package, name)) for name in _GROUP_NAMES},
            "disputed_count": len(package.disputed),
            "serialized_bytes": package.serialized_bytes,
            "max_serialized_bytes": bounds.max_serialized_bytes,
        },
    )
    return package
