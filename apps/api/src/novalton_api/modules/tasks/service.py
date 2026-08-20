"""Task application rules and transaction boundary."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.projects import repository as projects_repository
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.runtime_events.service import append_event
from novalton_api.modules.tasks import repository
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tasks.schemas import TaskCreate, TaskStatus, TaskUpdate
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


async def _require_scope(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, project_id: UUID
) -> None:
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if workspace is None:
        raise _not_found()
    project = await projects_repository.get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if project is None:
        raise _not_found()


async def create_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    data: TaskCreate,
) -> Task:
    await _require_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    try:
        task = await repository.create_task(
            session,
            project_id=project_id,
            title=data.title,
            description=data.description,
            status=data.status.value,
        )
        await append_event(
            session,
            data=RuntimeEventCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task.id,
                event_type="task.created",
                source="task_service",
                payload={"status": data.status.value},
            ),
            commit=False,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _not_found() from None
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    limit: int,
    offset: int,
    status: TaskStatus | None,
) -> list[Task]:
    await _require_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    return await repository.list_tasks(
        session,
        project_id=project_id,
        limit=limit,
        offset=offset,
        status=status.value if status is not None else None,
    )


async def get_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
) -> Task:
    await _require_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    task = await repository.get_task(session, project_id=project_id, task_id=task_id)
    if task is None:
        raise _not_found()
    return task


async def update_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
    data: TaskUpdate,
) -> Task:
    await _require_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    changes = data.model_dump(exclude_unset=True)
    if "status" in changes:
        changes["status"] = changes["status"].value
    try:
        task = await repository.update_task(
            session, project_id=project_id, task_id=task_id, changes=changes
        )
        if task is None:
            raise _not_found()
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project_id,
                task_id=task_id,
                resource_type="task",
                resource_id=task_id,
                action="task.update",
                actor_type="api",
                outcome="success",
                metadata={"changed_fields": sorted(changes)},
            ),
            commit=False,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _not_found() from None
    await session.refresh(task)
    return task


async def delete_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    task_id: UUID,
) -> None:
    await _require_scope(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    deleted = await repository.delete_task(session, project_id=project_id, task_id=task_id)
    if not deleted:
        raise _not_found()
    await session.commit()
