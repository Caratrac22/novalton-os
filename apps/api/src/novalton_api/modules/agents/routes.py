"""Scoped agent-definition management and read-only run diagnostics."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.agents import service
from novalton_api.modules.agents.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionListResponse,
    AgentDefinitionResponse,
    AgentDefinitionVersionCreate,
    AgentRunListResponse,
    AgentRunResponse,
    AgentRunStatus,
)

Session = Annotated[AsyncSession, Depends(get_async_session)]
definitions_router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/agents", tags=["agents"]
)
runs_router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/agent-runs", tags=["agent-runs"]
)


@definitions_router.post(
    "", response_model=AgentDefinitionResponse, status_code=status.HTTP_201_CREATED
)
async def create_definition(
    tenant_id: UUID, workspace_id: UUID, data: AgentDefinitionCreate, session: Session
) -> AgentDefinitionResponse:
    return AgentDefinitionResponse.model_validate(
        await service.create_definition(
            session, tenant_id=tenant_id, workspace_id=workspace_id, data=data
        )
    )


@definitions_router.post(
    "/{agent_definition_id}/versions",
    response_model=AgentDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    tenant_id: UUID,
    workspace_id: UUID,
    agent_definition_id: UUID,
    data: AgentDefinitionVersionCreate,
    session: Session,
) -> AgentDefinitionResponse:
    return AgentDefinitionResponse.model_validate(
        await service.create_version(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            definition_id=agent_definition_id,
            data=data,
        )
    )


@definitions_router.get("", response_model=AgentDefinitionListResponse)
async def list_definitions(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    all_versions: bool = False,
) -> AgentDefinitionListResponse:
    items = await service.list_definitions(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        all_versions=all_versions,
    )
    return AgentDefinitionListResponse(
        items=[AgentDefinitionResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
    )


@definitions_router.get("/{agent_definition_id}", response_model=AgentDefinitionResponse)
async def get_definition(
    tenant_id: UUID, workspace_id: UUID, agent_definition_id: UUID, session: Session
) -> AgentDefinitionResponse:
    return AgentDefinitionResponse.model_validate(
        await service.get_definition(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            definition_id=agent_definition_id,
        )
    )


@runs_router.get("", response_model=AgentRunListResponse)
async def list_runs(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[AgentRunStatus | None, Query(alias="status")] = None,
) -> AgentRunListResponse:
    items = await service.list_runs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return AgentRunListResponse(
        items=[AgentRunResponse.model_validate(item) for item in items],
        limit=limit,
        offset=offset,
    )


@runs_router.get("/{agent_run_id}", response_model=AgentRunResponse)
async def get_run(
    tenant_id: UUID, workspace_id: UUID, agent_run_id: UUID, session: Session
) -> AgentRunResponse:
    return AgentRunResponse.model_validate(
        await service.get_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=agent_run_id
        )
    )
