"""Application rules and transaction boundary for structured memory."""

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.memories import repository
from novalton_api.modules.memories.models import MemoryProvenance, MemoryRecord
from novalton_api.modules.memories.schemas import (
    KnowledgeState,
    MemoryCreate,
    MemoryKind,
    MemoryLifecycle,
)
from novalton_api.modules.projects import repository as projects_repository
from novalton_api.modules.tasks import repository as tasks_repository
from novalton_api.modules.workflows import repository as workflows_repository
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _invalid_memory(message: str) -> ApplicationError:
    return ApplicationError("invalid_memory", message, status_code=422)


async def _require_workspace(session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> None:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
    ) is None:
        raise _not_found()


async def _validate_links(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: MemoryCreate
) -> None:
    project = None
    if data.project_id is not None:
        project = await projects_repository.get_project(
            session, workspace_id=workspace_id, project_id=data.project_id
        )
        if project is None:
            raise _not_found()
    if data.task_id is not None:
        task = await tasks_repository.get_task(
            session, project_id=data.project_id, task_id=data.task_id
        )
        if task is None:
            raise _not_found()
    if data.workflow_run_id is not None:
        run = await workflows_repository.get_run(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=data.workflow_run_id,
        )
        if run is None:
            raise _not_found()
        if data.project_id is not None and run.project_id != data.project_id:
            raise _invalid_memory("workflow_run_id does not belong to project_id")
        if data.task_id is not None and run.task_id != data.task_id:
            raise _invalid_memory("workflow_run_id does not belong to task_id")


async def create_memory(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: MemoryCreate
) -> MemoryRecord:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    await _validate_links(session, tenant_id=tenant_id, workspace_id=workspace_id, data=data)
    memory = MemoryRecord(
        workspace_id=workspace_id,
        project_id=data.project_id,
        task_id=data.task_id,
        workflow_run_id=data.workflow_run_id,
        kind=data.kind.value,
        knowledge_state=data.knowledge_state.value,
        statement=data.statement,
        confidence=data.confidence,
        importance=data.importance,
        valid_from=data.valid_from,
        valid_to=data.valid_to,
        lifecycle=data.lifecycle.value,
        provenance=[
            MemoryProvenance(
                source_type=item.source_type.value,
                source_reference_id=item.source_reference_id,
            )
            for item in data.provenance
        ],
    )
    try:
        await repository.create_memory(session, memory=memory)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _invalid_memory("Memory could not be persisted") from None
    await session.refresh(memory, attribute_names=["provenance"])
    logger.info(
        "Structured memory created",
        extra={
            "event": "memory.created",
            "memory_id": str(memory.id),
            "workspace_id": str(workspace_id),
            "kind": memory.kind,
            "knowledge_state": memory.knowledge_state,
            "provenance_count": len(memory.provenance),
        },
    )
    return memory


async def get_memory(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, memory_id: UUID
) -> MemoryRecord:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    memory = await repository.get_memory(session, workspace_id=workspace_id, memory_id=memory_id)
    if memory is None:
        raise _not_found()
    return memory


async def list_memories(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    project_id: UUID | None,
    task_id: UUID | None,
    workflow_run_id: UUID | None,
    kind: MemoryKind | None,
    knowledge_state: KnowledgeState | None,
    lifecycle: MemoryLifecycle | None,
) -> list[MemoryRecord]:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await repository.list_memories(
        session,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        project_id=project_id,
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        kind=kind.value if kind is not None else None,
        knowledge_state=knowledge_state.value if knowledge_state is not None else None,
        lifecycle=lifecycle.value if lifecycle is not None else None,
    )
