import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings
from novalton_api.core.context import reset_correlation_id, set_correlation_id
from novalton_api.core.database import Base, Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.projects import service as project_service
from novalton_api.modules.projects.models import Project
from novalton_api.modules.projects.schemas import ProjectCreate
from novalton_api.modules.runtime_events import repository, service
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class EventScope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID


async def _reset() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(RuntimeEvent))
            await session.execute(delete(Task))
            await session.execute(delete(Project))
            await session.execute(delete(Workspace))
            await session.execute(delete(Tenant))
    finally:
        await database.dispose()


async def _seed() -> tuple[EventScope, EventScope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            scopes: list[EventScope] = []
            for number in (1, 2):
                tenant = Tenant(name=f"Tenant {number}", slug=f"tenant-{number}-{uuid4().hex[:6]}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(
                    tenant_id=tenant.id, name=f"Workspace {number}", slug=f"workspace-{number}"
                )
                session.add(workspace)
                await session.flush()
                project = Project(
                    workspace_id=workspace.id,
                    name=f"Project {number}",
                    slug=f"project-{number}",
                    status="ACTIVE",
                )
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title=f"Task {number}", status="BACKLOG")
                session.add(task)
                await session.flush()
                scopes.append(EventScope(tenant.id, workspace.id, project.id, task.id))
            return scopes[0], scopes[1]
    finally:
        await database.dispose()


@pytest.fixture
def event_scopes() -> tuple[EventScope, EventScope]:
    asyncio.run(_reset())
    scopes = asyncio.run(_seed())
    yield scopes
    asyncio.run(_reset())


def _event_data(scope: EventScope, **changes: object) -> RuntimeEventCreate:
    values: dict[str, object] = {
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "task_id": scope.task_id,
        "event_type": "task.created",
        "source": "test_service",
        "payload": {"status": "BACKLOG"},
    }
    values.update(changes)
    return RuntimeEventCreate.model_validate(values)


def test_runtime_event_metadata_is_scoped_and_append_oriented() -> None:
    table = Base.metadata.tables["runtime_events"]
    constraints = {constraint.name for constraint in table.constraints}
    assert table.c.id.primary_key
    assert not table.c.tenant_id.nullable
    assert not table.c.workspace_id.nullable
    assert table.c.project_id.nullable
    assert table.c.task_id.nullable
    assert table.c.occurred_at.type.timezone is True
    assert isinstance(table.c.payload.type, JSONB)
    assert {
        "fk_runtime_events_tenant_id_tenants",
        "fk_runtime_events_workspace_id_workspaces",
        "fk_runtime_events_project_id_projects",
        "fk_runtime_events_task_id_tasks",
        "ck_runtime_events_event_type_length",
        "ck_runtime_events_source_length",
        "ck_runtime_events_correlation_id_length",
        "ck_runtime_events_task_requires_project",
    }.issubset(constraints)
    assert not hasattr(repository, "update_event")
    assert not hasattr(repository, "delete_event")
    assert not hasattr(service, "update_event")
    assert not hasattr(service, "delete_event")


@pytest.mark.asyncio
async def test_append_event_persists_payload_and_context_correlation(
    event_scopes: tuple[EventScope, EventScope],
) -> None:
    first, _ = event_scopes
    database = Database.from_settings(Settings())
    token = set_correlation_id("req-runtime-123")
    try:
        async with database.session_factory() as session:
            event = await service.append_event(session, data=_event_data(first))
            event_id = event.id
        async with database.session_factory() as session:
            stored = await session.get(RuntimeEvent, event_id)
            assert stored is not None
            assert stored.tenant_id == first.tenant_id
            assert stored.workspace_id == first.workspace_id
            assert stored.project_id == first.project_id
            assert stored.task_id == first.task_id
            assert stored.correlation_id == "req-runtime-123"
            assert stored.payload == {"status": "BACKLOG"}
            assert stored.occurred_at.tzinfo is not None
    finally:
        reset_correlation_id(token)
        await database.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_type", "Task Created"),
        ("event_type", "task"),
        ("event_type", "Task.created"),
        ("source", "Task Service"),
        ("source", "task-service"),
        ("correlation_id", "bad correlation"),
    ],
)
def test_event_identifiers_are_strict(field: str, value: str) -> None:
    scope = EventScope(uuid4(), uuid4(), uuid4(), uuid4())
    with pytest.raises(ValidationError):
        _event_data(scope, **{field: value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"api_key": "value"},
        {"metadata": {"clientSecretValue": "value"}},
        {"nested": {"Authorization": "Bearer value"}},
        {"url": "https://user:password@example.test/path"},
        {"url": "https://example.test/path?access_token=value"},
        {"object": uuid4()},
        {"number": float("nan")},
        {"text": "x" * 8193},
    ],
)
async def test_payload_rejects_secrets_non_json_and_oversize(
    event_scopes: tuple[EventScope, EventScope], payload: dict[str, object]
) -> None:
    first, _ = event_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.append_event(session, data=_event_data(first, payload=payload))
            assert error.value.code == "invalid_runtime_event"
        async with database.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(RuntimeEvent)) == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_scope_and_resource_chain_reject_cross_scope_associations(
    event_scopes: tuple[EventScope, EventScope],
) -> None:
    first, second = event_scopes
    invalid = [
        _event_data(first, tenant_id=second.tenant_id),
        _event_data(first, workspace_id=second.workspace_id),
        _event_data(first, project_id=second.project_id, task_id=None),
        _event_data(first, task_id=second.task_id),
    ]
    database = Database.from_settings(Settings())
    try:
        for data in invalid:
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError) as error:
                    await service.append_event(session, data=data)
                assert error.value.code == "resource_not_found"
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.append_event(
                    session, data=_event_data(first, project_id=None, task_id=first.task_id)
                )
            assert error.value.code == "invalid_runtime_event"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failed_event_flush_rolls_back_and_sanitizes_database_error(
    event_scopes: tuple[EventScope, EventScope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = event_scopes
    database = Database.from_settings(Settings())
    secret = "raw-database-password"

    async def fail(*args: object, **kwargs: object) -> RuntimeEvent:
        raise IntegrityError("statement", {}, Exception(secret))

    monkeypatch.setattr(repository, "append_event", fail)
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.append_event(session, data=_event_data(first))
            assert error.value.code == "runtime_event_persistence_failed"
            assert secret not in error.value.message
            assert not session.in_transaction()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_project_event_failure_rolls_back_business_mutation(
    event_scopes: tuple[EventScope, EventScope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = event_scopes
    database = Database.from_settings(Settings())

    async def fail(*args: object, **kwargs: object) -> RuntimeEvent:
        raise IntegrityError("statement", {}, Exception("private database detail"))

    monkeypatch.setattr(repository, "append_event", fail)
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await project_service.create_project(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=ProjectCreate(name="Atomic", slug="atomic"),
                )
            assert error.value.code == "runtime_event_persistence_failed"
        async with database.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count()).select_from(Project).where(Project.slug == "atomic")
                )
                == 0
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_recent_retrieval_is_bounded_newest_first_and_scoped(
    event_scopes: tuple[EventScope, EventScope],
) -> None:
    first, second = event_scopes
    database = Database.from_settings(Settings())
    now = datetime.now(UTC)
    try:
        async with database.session_factory() as session:
            oldest = await service.append_event(
                session,
                data=_event_data(first, event_type="task.started"),
                occurred_at=now - timedelta(seconds=1),
            )
            newest = await service.append_event(
                session, data=_event_data(first, event_type="task.completed"), occurred_at=now
            )
            await service.append_event(session, data=_event_data(second))
            events = await service.list_recent_events(
                session, tenant_id=first.tenant_id, workspace_id=first.workspace_id, limit=2
            )
            assert [event.id for event in events] == [newest.id, oldest.id]
            with pytest.raises(ApplicationError):
                await service.list_recent_events(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    limit=101,
                )
    finally:
        await database.dispose()
