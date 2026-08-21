"""Scoped convenience API for the governed Developer Worker Agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.developer_worker import service
from novalton_api.modules.developer_worker.schemas import (
    DeveloperWorkerExecutionRequest,
    DeveloperWorkerExecutionResponse,
)

Session = Annotated[AsyncSession, Depends(get_async_session)]
router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/developer-worker",
    tags=["developer-worker"],
)


@router.post("/execute", response_model=DeveloperWorkerExecutionResponse)
async def execute_assignment(
    tenant_id: UUID,
    workspace_id: UUID,
    data: DeveloperWorkerExecutionRequest,
    session: Session,
    request: Request,
) -> DeveloperWorkerExecutionResponse:
    return await service.execute_assignment(
        session,
        registry=request.app.state.provider_registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )
