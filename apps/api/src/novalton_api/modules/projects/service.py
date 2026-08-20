"""Project application rules and transaction boundary."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.projects import repository
from novalton_api.modules.projects.models import Project
from novalton_api.modules.projects.schemas import ProjectCreate, ProjectUpdate
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.runtime_events.service import append_event
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _slug_conflict() -> ApplicationError:
    return ApplicationError(
        "project_slug_conflict",
        "A project with this slug already exists in the workspace",
        status_code=409,
    )


async def _require_workspace(session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> None:
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if workspace is None:
        raise _not_found()


async def _require_project(
    session: AsyncSession, *, workspace_id: UUID, project_id: UUID
) -> Project:
    project = await repository.get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if project is None:
        raise _not_found()
    return project


async def create_project(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: ProjectCreate
) -> Project:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    try:
        project = await repository.create_project(
            session,
            workspace_id=workspace_id,
            name=data.name,
            slug=data.slug,
            description=data.description,
            status=data.status.value,
        )
        await append_event(
            session,
            data=RuntimeEventCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project.id,
                event_type="project.created",
                source="project_service",
                payload={"status": data.status.value},
            ),
            commit=False,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _slug_conflict() from None
    await session.refresh(project)
    return project


async def list_projects(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> list[Project]:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await repository.list_projects(
        session, workspace_id=workspace_id, limit=limit, offset=offset
    )


async def get_project(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, project_id: UUID
) -> Project:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await _require_project(session, workspace_id=workspace_id, project_id=project_id)


async def update_project(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    data: ProjectUpdate,
) -> Project:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    changes = data.model_dump(exclude_unset=True)
    if "status" in changes:
        changes["status"] = changes["status"].value
    try:
        project = await repository.update_project(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            changes=changes,
        )
        if project is None:
            raise _not_found()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _slug_conflict() from None
    await session.refresh(project)
    return project


async def delete_project(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, project_id: UUID
) -> None:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    deleted = await repository.delete_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if not deleted:
        raise _not_found()
    await session.commit()
