"""Scoped persistence queries for durable Git changesets."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.git_changesets.models import GitCommitAction


async def get_scoped(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    action_id: UUID,
    for_update: bool = False,
) -> GitCommitAction | None:
    statement = select(GitCommitAction).where(
        GitCommitAction.id == action_id,
        GitCommitAction.tenant_id == tenant_id,
        GitCommitAction.workspace_id == workspace_id,
    )
    return await session.scalar(statement.with_for_update() if for_update else statement)


async def get_for_approval(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    approval_id: UUID,
    for_update: bool = False,
) -> GitCommitAction | None:
    statement = select(GitCommitAction).where(
        GitCommitAction.approval_request_id == approval_id,
        GitCommitAction.tenant_id == tenant_id,
        GitCommitAction.workspace_id == workspace_id,
    )
    return await session.scalar(statement.with_for_update() if for_update else statement)


async def list_for_workflow(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, workflow_run_id: UUID
) -> list[GitCommitAction]:
    return list(
        (
            await session.scalars(
                select(GitCommitAction)
                .where(
                    GitCommitAction.tenant_id == tenant_id,
                    GitCommitAction.workspace_id == workspace_id,
                    GitCommitAction.workflow_run_id == workflow_run_id,
                )
                .order_by(GitCommitAction.created_at, GitCommitAction.id)
            )
        ).all()
    )
