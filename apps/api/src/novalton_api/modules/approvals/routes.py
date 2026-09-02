"""Thin tenant/workspace-scoped approval HTTP routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.approvals import mutation_resume, service
from novalton_api.modules.approvals.schemas import (
    ApprovalCreate,
    ApprovalListResponse,
    ApprovalResponse,
    ApprovalStatus,
)
from novalton_api.modules.git_changesets import repository as git_repository
from novalton_api.modules.git_changesets import service as git_service

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/approvals",
    tags=["approvals"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post("", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    tenant_id: UUID,
    workspace_id: UUID,
    data: ApprovalCreate,
    session: Session,
) -> ApprovalResponse:
    approval = await service.create_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, data=data
    )
    return ApprovalResponse.model_validate(approval)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
) -> ApprovalListResponse:
    approvals = await service.list_approvals(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=approval_status,
    )
    return ApprovalListResponse(items=approvals, limit=limit, offset=offset)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    session: Session,
) -> ApprovalResponse:
    approval = await service.get_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve(
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    session: Session,
    request: Request,
) -> ApprovalResponse:
    current = await service.get_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    git_action = await git_repository.get_for_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    if git_action is not None:
        approval = await service.approve(
            session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
        )
        await git_service.approve_and_apply(
            session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
        )
    elif current.mutation_fingerprint is not None:
        approval = await mutation_resume.approve_and_resume(
            session,
            registry=request.app.state.provider_registry,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            approval_id=approval_id,
        )
    else:
        approval = await service.approve(
            session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
        )
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject(
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    session: Session,
) -> ApprovalResponse:
    current = await service.get_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    git_action = await git_repository.get_for_approval(
        session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
    )
    if git_action is not None:
        approval = await service.reject(
            session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
        )
        git_action.status = "REJECTED"
        await session.commit()
    elif current.mutation_fingerprint is not None:
        approval = await mutation_resume.reject_and_terminalize(
            session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
        )
    else:
        approval = await service.reject(
            session, tenant_id=tenant_id, workspace_id=workspace_id, approval_id=approval_id
        )
    return ApprovalResponse.model_validate(approval)
