"""Versioning, strict scope validation, and deterministic run lifecycle."""

import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.agents import repository
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionVersionCreate,
    AgentRunCreate,
    AgentRunStatus,
)
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.model_usage.repository import get_scoped_run as get_model_run
from novalton_api.modules.projects.repository import get_project
from novalton_api.modules.tasks.repository import get_task
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)
_FAILURE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


async def _scope(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID | None = None,
    task_id: UUID | None = None,
) -> None:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise _not_found()
    if (
        project_id is not None
        and await get_project(session, workspace_id=workspace_id, project_id=project_id) is None
    ):
        raise _not_found()
    if task_id is not None and (
        project_id is None
        or await get_task(session, project_id=project_id, task_id=task_id) is None
    ):
        raise _not_found()


async def create_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: AgentDefinitionCreate
) -> AgentDefinition:
    await _scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    if (
        await repository.latest_definition(
            session, tenant_id=tenant_id, workspace_id=workspace_id, slug=data.slug
        )
        is not None
    ):
        raise ApplicationError("agent_slug_exists", "Agent slug already exists", status_code=409)
    try:
        definition = await repository.create_definition(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            slug=data.slug,
            version=1,
            **data.model_dump(exclude={"slug"}, mode="json"),
        )
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                action="agent.definition.created",
                actor_type="service",
                outcome="success",
                metadata={
                    "agent_definition_id": str(definition.id),
                    "agent_slug": definition.slug,
                    "agent_version": definition.version,
                },
            ),
            commit=False,
        )
        await session.commit()
        await session.refresh(definition)
    except IntegrityError:
        await session.rollback()
        raise ApplicationError(
            "agent_slug_exists", "Agent slug already exists", status_code=409
        ) from None
    logger.info(
        "Agent definition created",
        extra={
            "event": "agent.definition.created",
            "agent_definition_id": str(definition.id),
            "agent_slug": definition.slug,
            "agent_version": definition.version,
            "tenant_id": str(tenant_id),
            "workspace_id": str(workspace_id),
        },
    )
    return definition


async def create_version(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    definition_id: UUID,
    data: AgentDefinitionVersionCreate,
) -> AgentDefinition:
    await _scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    source = await repository.get_definition(
        session, tenant_id=tenant_id, workspace_id=workspace_id, definition_id=definition_id
    )
    if source is None:
        raise _not_found()
    latest = await repository.latest_definition(
        session, tenant_id=tenant_id, workspace_id=workspace_id, slug=source.slug
    )
    if latest is None:
        raise _not_found()
    try:
        definition = await repository.create_definition(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            slug=source.slug,
            version=latest.version + 1,
            **data.model_dump(mode="json"),
        )
        await append_record(
            session,
            data=AuditRecordCreate(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                action="agent.definition.versioned",
                actor_type="service",
                outcome="success",
                metadata={
                    "agent_definition_id": str(definition.id),
                    "agent_slug": definition.slug,
                    "agent_version": definition.version,
                    "previous_version": latest.version,
                },
            ),
            commit=False,
        )
        await session.commit()
        await session.refresh(definition)
    except IntegrityError:
        await session.rollback()
        raise ApplicationError(
            "agent_version_conflict", "Agent version creation conflicted", status_code=409
        ) from None
    logger.info(
        "Agent definition version created",
        extra={
            "event": "agent.definition.versioned",
            "agent_definition_id": str(definition.id),
            "agent_slug": definition.slug,
            "agent_version": definition.version,
            "tenant_id": str(tenant_id),
            "workspace_id": str(workspace_id),
        },
    )
    return definition


async def get_definition(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, definition_id: UUID
) -> AgentDefinition:
    await _scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    value = await repository.get_definition(
        session, tenant_id=tenant_id, workspace_id=workspace_id, definition_id=definition_id
    )
    if value is None:
        raise _not_found()
    return value


async def list_definitions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    all_versions: bool,
) -> list[AgentDefinition]:
    await _scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await repository.list_definitions(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        all_versions=all_versions,
    )


async def create_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, data: AgentRunCreate
) -> AgentRun:
    await _scope(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=data.project_id,
        task_id=data.task_id,
    )
    definition = await repository.get_definition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        definition_id=data.agent_definition_id,
    )
    if definition is None:
        raise _not_found()
    if data.parent_agent_run_id is not None:
        parent = await repository.get_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=data.parent_agent_run_id
        )
        if parent is None or (parent.project_id, parent.task_id) != (data.project_id, data.task_id):
            raise _not_found()
    if data.model_run_id is not None:
        model_run = await get_model_run(
            session, tenant_id=tenant_id, workspace_id=workspace_id, model_run_id=data.model_run_id
        )
        if model_run is None or model_run.project_id != data.project_id:
            raise _not_found()
    run = await repository.create_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=data.project_id,
        task_id=data.task_id,
        agent_definition_id=definition.id,
        agent_version=definition.version,
        agent_name=definition.name,
        agent_slug=definition.slug,
        parent_agent_run_id=data.parent_agent_run_id,
        model_run_id=data.model_run_id,
        status=AgentRunStatus.CREATED.value,
        correlation_id=get_correlation_id(),
    )
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> AgentRun:
    await _scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    run = await repository.get_run(
        session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id
    )
    if run is None:
        raise _not_found()
    return run


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    status: AgentRunStatus | None,
) -> list[AgentRun]:
    await _scope(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await repository.list_runs(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        status=status.value if status else None,
    )


async def _transition(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    run_id: UUID,
    expected: AgentRunStatus,
    target: AgentRunStatus,
    failure_code: str | None = None,
) -> AgentRun:
    await get_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id)
    now = datetime.now(UTC)
    values: dict[str, object] = {"status": target.value, "updated_at": now}
    if target == AgentRunStatus.RUNNING:
        values["started_at"] = now
    elif target in {AgentRunStatus.SUCCEEDED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
        values["completed_at"] = now
        values["failure_code"] = failure_code
    updated = await repository.transition_run(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected_status=expected.value,
        values=values,
    )
    if updated is None:
        raise ApplicationError(
            "agent_run_invalid_transition", "Agent run state transition is invalid", status_code=409
        )
    await session.commit()
    return updated


async def start_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> AgentRun:
    return await _transition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected=AgentRunStatus.CREATED,
        target=AgentRunStatus.RUNNING,
    )


async def succeed_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> AgentRun:
    return await _transition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected=AgentRunStatus.RUNNING,
        target=AgentRunStatus.SUCCEEDED,
    )


async def fail_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID, failure_code: str
) -> AgentRun:
    if _FAILURE.fullmatch(failure_code) is None:
        raise ApplicationError("agent_run_invalid_failure", "Failure code is invalid")
    return await _transition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected=AgentRunStatus.RUNNING,
        target=AgentRunStatus.FAILED,
        failure_code=failure_code,
    )


async def cancel_run(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, run_id: UUID
) -> AgentRun:
    run = await get_run(session, tenant_id=tenant_id, workspace_id=workspace_id, run_id=run_id)
    if run.status == AgentRunStatus.CREATED.value:
        return await _transition(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run_id,
            expected=AgentRunStatus.CREATED,
            target=AgentRunStatus.CANCELLED,
        )
    return await _transition(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        run_id=run_id,
        expected=AgentRunStatus.RUNNING,
        target=AgentRunStatus.CANCELLED,
    )
