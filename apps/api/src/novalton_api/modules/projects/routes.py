"""Thin HTTP routes for workspace-scoped projects."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.projects import service
from novalton_api.modules.projects.schemas import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/projects",
    tags=["projects"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    tenant_id: UUID, workspace_id: UUID, data: ProjectCreate, session: Session
) -> ProjectResponse:
    project = await service.create_project(
        session, tenant_id=tenant_id, workspace_id=workspace_id, data=data
    )
    return ProjectResponse.model_validate(project)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectListResponse:
    projects = await service.list_projects(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(items=projects, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    tenant_id: UUID, workspace_id: UUID, project_id: UUID, session: Session
) -> ProjectResponse:
    project = await service.get_project(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    data: ProjectUpdate,
    session: Session,
) -> ProjectResponse:
    project = await service.update_project(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        data=data,
    )
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    tenant_id: UUID, workspace_id: UUID, project_id: UUID, session: Session
) -> Response:
    await service.delete_project(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
