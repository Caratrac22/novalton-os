from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.modules.github_publications import service
from novalton_api.modules.github_publications.config import (
    resolve_github_credential,
    trusted_binding,
)
from novalton_api.modules.github_publications.http_adapter import GitHubHttpAdapter
from novalton_api.modules.github_publications.schemas import (
    GitHubPublicationActionResponse,
    GitHubPublicationCreate,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/git-commit-actions",
    tags=["github-publications"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


@router.post(
    "/{git_commit_action_id}/github-publications",
    response_model=GitHubPublicationActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare(
    tenant_id: UUID,
    workspace_id: UUID,
    git_commit_action_id: UUID,
    data: GitHubPublicationCreate,
    session: Session,
) -> GitHubPublicationActionResponse:
    adapter = GitHubHttpAdapter(trusted_binding(), resolve_github_credential())
    try:
        return GitHubPublicationActionResponse.model_validate(
            await service.prepare(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                git_commit_action_id=git_commit_action_id,
                data=data,
                adapter=adapter,
            )
        )
    finally:
        await adapter.aclose()
