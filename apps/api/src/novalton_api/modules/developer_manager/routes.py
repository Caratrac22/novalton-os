"""Scoped convenience API for the governed Developer Manager Agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.developer_manager import service
from novalton_api.modules.developer_manager.schemas import (
    DeveloperManagerPlanningRequest,
    DeveloperManagerPlanningResponse,
)

Session = Annotated[AsyncSession, Depends(get_async_session)]
router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/developer-manager",
    tags=["developer-manager"],
)


@router.post("/plan", response_model=DeveloperManagerPlanningResponse)
async def create_plan_proposal(
    tenant_id: UUID,
    workspace_id: UUID,
    data: DeveloperManagerPlanningRequest,
    session: Session,
    request: Request,
) -> DeveloperManagerPlanningResponse:
    return await service.plan(
        session,
        registry=request.app.state.provider_registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )
