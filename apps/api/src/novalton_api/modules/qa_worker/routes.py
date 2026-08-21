"""Scoped convenience API for the governed QA Worker Agent."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.qa_worker import service
from novalton_api.modules.qa_worker.schemas import (
    QAWorkerValidationRequest,
    QAWorkerValidationResponse,
)

Session = Annotated[AsyncSession, Depends(get_async_session)]
router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/qa-worker",
    tags=["qa-worker"],
)


@router.post("/validate", response_model=QAWorkerValidationResponse)
async def validate(
    tenant_id: UUID,
    workspace_id: UUID,
    data: QAWorkerValidationRequest,
    session: Session,
    request: Request,
) -> QAWorkerValidationResponse:
    return await service.validate(
        session,
        registry=request.app.state.provider_registry,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        data=data,
    )
