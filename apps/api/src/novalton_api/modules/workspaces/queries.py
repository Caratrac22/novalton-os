"""Tenant-scoped workspace queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.workspaces.models import Workspace


async def get_workspace_by_tenant_and_slug(
    session: AsyncSession, *, tenant_id: UUID, slug: str
) -> Workspace | None:
    """Find a workspace without allowing an unscoped slug lookup."""
    return await session.scalar(
        select(Workspace).where(Workspace.tenant_id == tenant_id, Workspace.slug == slug)
    )


async def get_workspace_by_tenant_and_id(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID
) -> Workspace | None:
    """Find a workspace only through its owning tenant."""
    return await session.scalar(
        select(Workspace).where(
            Workspace.tenant_id == tenant_id,
            Workspace.id == workspace_id,
        )
    )
