"""Scoped, non-executing model routing diagnostics."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.model_router import service
from novalton_api.modules.model_router.schemas import RoutingRequest, RoutingSimulationResult

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/models/route",
    tags=["models"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post("/simulate", response_model=RoutingSimulationResult)
async def simulate_route(
    tenant_id: UUID,
    workspace_id: UUID,
    data: RoutingRequest,
    session: Session,
    request: Request,
) -> RoutingSimulationResult:
    return await service.simulate(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
        virtual_routes=request.app.state.provider_registry.provider_managed_routes,
    )
