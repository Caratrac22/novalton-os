"""HTTP routes for tenant/workspace-scoped structured memory."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.memories import service
from novalton_api.modules.memories.schemas import (
    KnowledgeState,
    MemoryCreate,
    MemoryKind,
    MemoryLifecycle,
    MemoryListResponse,
    MemoryResponse,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
    MemoryRetrievalResult,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/memories", tags=["memories"]
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    tenant_id: UUID, workspace_id: UUID, data: MemoryCreate, session: Session
) -> MemoryResponse:
    return MemoryResponse.model_validate(
        await service.create_memory(
            session, tenant_id=tenant_id, workspace_id=workspace_id, data=data
        )
    )


@router.post("/retrieve", response_model=MemoryRetrievalResponse)
async def retrieve_memories(
    tenant_id: UUID, workspace_id: UUID, data: MemoryRetrievalRequest, session: Session
) -> MemoryRetrievalResponse:
    memories, as_of = await service.retrieve_memories(
        session, tenant_id=tenant_id, workspace_id=workspace_id, data=data
    )
    return MemoryRetrievalResponse(
        items=[MemoryRetrievalResult.model_validate(memory) for memory in memories],
        limit=data.limit,
        as_of=as_of,
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    tenant_id: UUID, workspace_id: UUID, memory_id: UUID, session: Session
) -> MemoryResponse:
    return MemoryResponse.model_validate(
        await service.get_memory(
            session, tenant_id=tenant_id, workspace_id=workspace_id, memory_id=memory_id
        )
    )


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    workflow_run_id: UUID | None = None,
    kind: MemoryKind | None = None,
    knowledge_state: KnowledgeState | None = None,
    lifecycle: MemoryLifecycle | None = None,
) -> MemoryListResponse:
    memories = await service.list_memories(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        project_id=project_id,
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        kind=kind,
        knowledge_state=knowledge_state,
        lifecycle=lifecycle,
    )
    return MemoryListResponse(items=memories, limit=limit, offset=offset)
