"""Explicit project-scoped task queries."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.modules.tasks.models import Task


async def create_task(
    session: AsyncSession,
    *,
    project_id: UUID,
    title: str,
    description: str | None,
    status: str,
) -> Task:
    task = Task(project_id=project_id, title=title, description=description, status=status)
    session.add(task)
    await session.flush()
    return task


async def list_tasks(
    session: AsyncSession,
    *,
    project_id: UUID,
    limit: int,
    offset: int,
    status: str | None,
) -> list[Task]:
    statement = select(Task).where(Task.project_id == project_id)
    if status is not None:
        statement = statement.where(Task.status == status)
    result = await session.scalars(
        statement.order_by(Task.created_at.asc(), Task.id.asc()).limit(limit).offset(offset)
    )
    return list(result)


async def get_task(session: AsyncSession, *, project_id: UUID, task_id: UUID) -> Task | None:
    return await session.scalar(
        select(Task).where(Task.project_id == project_id, Task.id == task_id)
    )


async def update_task(
    session: AsyncSession,
    *,
    project_id: UUID,
    task_id: UUID,
    changes: Mapping[str, Any],
) -> Task | None:
    return await session.scalar(
        update(Task)
        .where(Task.project_id == project_id, Task.id == task_id)
        .values(**changes)
        .returning(Task)
    )


async def delete_task(session: AsyncSession, *, project_id: UUID, task_id: UUID) -> bool:
    result = await session.execute(
        delete(Task).where(Task.project_id == project_id, Task.id == task_id)
    )
    return bool(result.rowcount)
