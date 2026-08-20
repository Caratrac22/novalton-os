"""Thin tenant/workspace-scoped policy simulation route."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.policy import simulation
from novalton_api.modules.policy.schemas import PolicySimulationRequest, PolicySimulationResult

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/policy",
    tags=["policy"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post("/simulate", response_model=PolicySimulationResult)
async def simulate_policy(
    tenant_id: UUID,
    workspace_id: UUID,
    data: PolicySimulationRequest,
    session: Session,
) -> PolicySimulationResult:
    return await simulation.simulate(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )
