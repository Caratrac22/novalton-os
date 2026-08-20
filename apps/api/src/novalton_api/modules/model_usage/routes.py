"""Read-only scoped model-run diagnostic routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.model_usage import service
from novalton_api.modules.model_usage.schemas import (
    ModelRunListResponse,
    ModelRunResponse,
    ModelRunStatus,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/model-runs", tags=["model-runs"]
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.get("", response_model=ModelRunListResponse)
async def list_model_runs(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[ModelRunStatus | None, Query()] = None,
) -> ModelRunListResponse:
    runs = await service.list_runs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return ModelRunListResponse(items=runs, limit=limit, offset=offset)


@router.get("/{model_run_id}", response_model=ModelRunResponse)
async def get_model_run(
    tenant_id: UUID, workspace_id: UUID, model_run_id: UUID, session: Session
) -> ModelRunResponse:
    return ModelRunResponse.model_validate(
        await service.get_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, model_run_id=model_run_id
        )
    )
