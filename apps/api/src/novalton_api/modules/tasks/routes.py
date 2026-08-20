"""Thin HTTP routes for project-scoped tasks."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.tasks import service
from novalton_api.modules.tasks.schemas import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
    TaskUpdate,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}/tasks",
    tags=["tasks"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    data: TaskCreate,
    session: Session,
) -> TaskResponse:
    task = await service.create_task(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        data=data,
    )
    return TaskResponse.model_validate(task)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = None,
) -> TaskListResponse:
    tasks = await service.list_tasks(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        limit=limit,
        offset=offset,
        status=task_status,
    )
    return TaskListResponse(items=tasks, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    session: Session,
) -> TaskResponse:
    task = await service.get_task(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
    )
    return TaskResponse.model_validate(task)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    data: TaskUpdate,
    session: Session,
) -> TaskResponse:
    task = await service.update_task(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        data=data,
    )
    return TaskResponse.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    session: Session,
) -> Response:
    await service.delete_task(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
