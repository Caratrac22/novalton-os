"""Narrow API for one orchestration advance cycle."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.orchestrator import challenge_service, service
from novalton_api.modules.orchestrator.schemas import (
    ChallengeResolutionRequest,
    ChallengeResolutionResponse,
    OrchestrationResult,
)

Session = Annotated[AsyncSession, Depends(get_async_session)]
router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/workflow-runs",
    tags=["orchestrator"],
)


@router.post("/{workflow_run_id}/advance", response_model=OrchestrationResult)
async def advance(
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    session: Session,
    request: Request,
) -> OrchestrationResult:
    if await request.body():
        raise ApplicationError(
            "invalid_orchestration_request",
            "The orchestration advance endpoint does not accept a request body",
            status_code=422,
        )
    return await service.advance(
        session,
        registry=request.app.state.provider_registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        workflow_run_id=workflow_run_id,
    )


@router.post(
    "/{workflow_run_id}/steps/{workflow_step_run_id}/challenge-resolution",
    response_model=ChallengeResolutionResponse,
)
async def resolve_challenge(
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    workflow_step_run_id: UUID,
    data: ChallengeResolutionRequest,
    session: Session,
) -> ChallengeResolutionResponse:
    """Resolve as the trusted local V1 user; actor authority is never caller supplied."""
    return await challenge_service.resolve(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        workflow_run_id=workflow_run_id,
        workflow_step_run_id=workflow_step_run_id,
        data=data,
    )
