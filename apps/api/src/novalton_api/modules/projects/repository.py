"""Explicit workspace-scoped project queries."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.projects.models import Project


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    name: str,
    slug: str,
    description: str | None,
    status: str,
) -> Project:
    project = Project(
        workspace_id=workspace_id,
        name=name,
        slug=slug,
        description=description,
        status=status,
    )
    session.add(project)
    await session.flush()
    return project


async def list_projects(
    session: AsyncSession, *, workspace_id: UUID, limit: int, offset: int
) -> list[Project]:
    result = await session.scalars(
        select(Project)
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.created_at.asc(), Project.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def get_project(
    session: AsyncSession, *, workspace_id: UUID, project_id: UUID
) -> Project | None:
    return await session.scalar(
        select(Project).where(Project.workspace_id == workspace_id, Project.id == project_id)
    )


async def update_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    changes: Mapping[str, Any],
) -> Project | None:
    return await session.scalar(
        update(Project)
        .where(Project.workspace_id == workspace_id, Project.id == project_id)
        .values(**changes)
        .returning(Project)
    )


async def delete_project(session: AsyncSession, *, workspace_id: UUID, project_id: UUID) -> bool:
    result = await session.execute(
        delete(Project).where(Project.workspace_id == workspace_id, Project.id == project_id)
    )
    return bool(result.rowcount)
