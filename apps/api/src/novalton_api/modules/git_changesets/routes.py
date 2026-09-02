"""Scoped post-QA operator routes for local Git commit actions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.git_changesets import repository, service
from novalton_api.modules.git_changesets.schemas import GitCommitActionResponse, GitCommitPrepare

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/workflow-runs", tags=["git-changesets"]
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post(
    "/{workflow_run_id}/git-commit-actions",
    response_model=GitCommitActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare(
    tenant_id: UUID,
    workspace_id: UUID,
    workflow_run_id: UUID,
    data: GitCommitPrepare,
    session: Session,
) -> GitCommitActionResponse:
    return GitCommitActionResponse.model_validate(
        await service.prepare(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_run_id=workflow_run_id,
            data=data,
        )
    )


@router.get("/{workflow_run_id}/git-commit-actions", response_model=list[GitCommitActionResponse])
async def list_actions(
    tenant_id: UUID, workspace_id: UUID, workflow_run_id: UUID, session: Session
) -> list[GitCommitActionResponse]:
    return [
        GitCommitActionResponse.model_validate(item)
        for item in await repository.list_for_workflow(
            session, tenant_id=tenant_id, workspace_id=workspace_id, workflow_run_id=workflow_run_id
        )
    ]
