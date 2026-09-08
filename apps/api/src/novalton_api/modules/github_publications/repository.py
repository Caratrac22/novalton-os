from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.github_publications.models import GitHubPublicationAction


async def get_for_commit(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    git_commit_action_id: UUID,
    for_update: bool = False,
) -> GitHubPublicationAction | None:
    query = select(GitHubPublicationAction).where(
        GitHubPublicationAction.tenant_id == tenant_id,
        GitHubPublicationAction.workspace_id == workspace_id,
        GitHubPublicationAction.git_commit_action_id == git_commit_action_id,
    )
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)


async def get_for_approval(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    for_update: bool = False,
) -> GitHubPublicationAction | None:
    query = select(GitHubPublicationAction).where(
        GitHubPublicationAction.tenant_id == tenant_id,
        GitHubPublicationAction.workspace_id == workspace_id,
        GitHubPublicationAction.approval_request_id == approval_id,
    )
    if for_update:
        query = query.with_for_update()
    return await session.scalar(query)
