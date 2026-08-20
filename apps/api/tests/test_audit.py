import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
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
from novalton_api.modules.audit import repository, service
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.projects import service as project_service
from novalton_api.modules.projects.models import Project
from novalton_api.modules.projects.schemas import ProjectUpdate
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks import service as task_service
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tasks.schemas import TaskUpdate
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class AuditScope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID


async def _reset() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(AuditRecord))
            await session.execute(delete(RuntimeEvent))
            await session.execute(delete(Task))
            await session.execute(delete(Project))
            await session.execute(delete(Workspace))
            await session.execute(delete(Tenant))
    finally:
        await database.dispose()


async def _seed() -> tuple[AuditScope, AuditScope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            scopes = []
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
                scopes.append(AuditScope(tenant.id, workspace.id, project.id, task.id))
            return scopes[0], scopes[1]
    finally:
        await database.dispose()


@pytest.fixture
def audit_scopes() -> tuple[AuditScope, AuditScope]:
    asyncio.run(_reset())
    scopes = asyncio.run(_seed())
    yield scopes
    asyncio.run(_reset())


def _record_data(scope: AuditScope, **changes: object) -> AuditRecordCreate:
    values: dict[str, object] = {
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "task_id": scope.task_id,
        "resource_type": "task",
        "resource_id": scope.task_id,
        "action": "task.update",
        "actor_type": "api",
        "outcome": "success",
        "metadata": {"changed_fields": ["status"]},
    }
    values.update(changes)
    return AuditRecordCreate.model_validate(values)


def test_audit_record_model_constraints_and_append_only_contract() -> None:
    table = Base.metadata.tables["audit_records"]
    constraints = {constraint.name for constraint in table.constraints}
    assert table.c.id.primary_key
    assert not table.c.tenant_id.nullable
    assert not table.c.workspace_id.nullable
    assert table.c.occurred_at.type.timezone is True
    assert isinstance(table.c.metadata_json.type, JSONB)
    assert {
        "ck_audit_records_action_length",
        "ck_audit_records_actor_type_value",
        "ck_audit_records_actor_id_length",
        "ck_audit_records_outcome_value",
        "ck_audit_records_resource_type_value",
        "ck_audit_records_resource_pair",
        "ck_audit_records_task_requires_project",
        "ck_audit_records_correlation_id_length",
        "fk_audit_records_tenant_id_tenants",
        "fk_audit_records_workspace_id_workspaces",
        "fk_audit_records_project_id_projects",
        "fk_audit_records_task_id_tasks",
    }.issubset(constraints)
    assert not hasattr(repository, "update_record")
    assert not hasattr(repository, "delete_record")
    assert not hasattr(service, "update_record")
    assert not hasattr(service, "delete_record")


@pytest.mark.asyncio
async def test_append_record_persists_accountability_and_correlation(
    audit_scopes: tuple[AuditScope, AuditScope],
) -> None:
    first, _ = audit_scopes
    database = Database.from_settings(Settings())
    token = set_correlation_id("req-audit-123")
    try:
        async with database.session_factory() as session:
            record = await service.append_record(session, data=_record_data(first))
            record_id = record.id
        async with database.session_factory() as session:
            stored = await session.get(AuditRecord, record_id)
            assert stored is not None
            assert (stored.actor_type, stored.actor_id) == ("api", None)
            assert (stored.action, stored.outcome) == ("task.update", "success")
            assert stored.resource_id == first.task_id
            assert stored.correlation_id == "req-audit-123"
            assert stored.metadata_json == {"changed_fields": ["status"]}
            assert stored.occurred_at.tzinfo is not None
    finally:
        reset_correlation_id(token)
        await database.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_type", "user"),
        ("action", "Task Update"),
        ("action", "task"),
        ("outcome", "ok"),
        ("resource_type", "email"),
        ("correlation_id", "bad correlation"),
    ],
)
def test_actor_action_outcome_and_references_are_strict(field: str, value: str) -> None:
    scope = AuditScope(uuid4(), uuid4(), uuid4(), uuid4())
    with pytest.raises(ValidationError):
        _record_data(scope, **{field: value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"password": "value"},
        {"request": {"Authorization": "value"}},
        {"email_body": "hello"},
        {"message": "full message"},
        {"url": "https://user:password@example.test/path"},
        {"url": "https://example.test/path?access_token=value"},
        {"header": "Bearer abcdefghijklmnop"},
        {"object": uuid4()},
        {"number": float("nan")},
        {"text": "x" * 257},
    ],
)
async def test_metadata_rejects_sensitive_or_unsafe_values(
    audit_scopes: tuple[AuditScope, AuditScope], metadata: dict[str, object]
) -> None:
    first, _ = audit_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.append_record(session, data=_record_data(first, metadata=metadata))
            assert error.value.code == "invalid_audit_record"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_scope_and_resource_chain_reject_cross_scope(
    audit_scopes: tuple[AuditScope, AuditScope],
) -> None:
    first, second = audit_scopes
    invalid = [
        _record_data(first, tenant_id=second.tenant_id),
        _record_data(first, workspace_id=second.workspace_id),
        _record_data(
            first,
            project_id=second.project_id,
            task_id=None,
            resource_type="project",
            resource_id=second.project_id,
        ),
        _record_data(first, task_id=second.task_id, resource_id=second.task_id),
    ]
    database = Database.from_settings(Settings())
    try:
        for data in invalid:
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError) as error:
                    await service.append_record(session, data=data)
                assert error.value.code == "resource_not_found"
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.append_record(
                    session,
                    data=_record_data(first, task_id=None),
                )
            assert error.value.code == "invalid_audit_record"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failure_rolls_back_and_sanitizes_persistence_error(
    audit_scopes: tuple[AuditScope, AuditScope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = audit_scopes
    database = Database.from_settings(Settings())
    secret = "raw-database-password"

    async def fail(*args: object, **kwargs: object) -> AuditRecord:
        raise IntegrityError("statement", {}, Exception(secret))

    monkeypatch.setattr(repository, "append_record", fail)
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.append_record(session, data=_record_data(first))
            assert error.value.code == "audit_persistence_failed"
            assert secret not in error.value.message
            assert not session.in_transaction()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_project_and_task_updates_append_atomic_audits(
    audit_scopes: tuple[AuditScope, AuditScope],
) -> None:
    first, _ = audit_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await project_service.update_project(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                data=ProjectUpdate(name="Renamed"),
            )
            await task_service.update_task(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                task_id=first.task_id,
                data=TaskUpdate(status="READY"),
            )
        async with database.session_factory() as session:
            records = await service.list_recent_records(
                session, tenant_id=first.tenant_id, workspace_id=first.workspace_id
            )
            assert {record.action for record in records} == {"project.update", "task.update"}
            assert all(
                record.actor_type == "api" and record.outcome == "success" for record in records
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_required_audit_failure_rolls_back_business_update(
    audit_scopes: tuple[AuditScope, AuditScope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = audit_scopes
    database = Database.from_settings(Settings())

    async def fail(*args: object, **kwargs: object) -> AuditRecord:
        raise IntegrityError("statement", {}, Exception("private database detail"))

    monkeypatch.setattr(repository, "append_record", fail)
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await project_service.update_project(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    project_id=first.project_id,
                    data=ProjectUpdate(name="Must Roll Back"),
                )
            assert error.value.code == "audit_persistence_failed"
        async with database.session_factory() as session:
            project = await session.get(Project, first.project_id)
            assert project is not None
            assert project.name != "Must Roll Back"
            assert await session.scalar(select(func.count()).select_from(AuditRecord)) == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_explicit_timezone_aware_occurrence_and_scoped_retrieval(
    audit_scopes: tuple[AuditScope, AuditScope],
) -> None:
    first, second = audit_scopes
    database = Database.from_settings(Settings())
    now = datetime.now(UTC)
    try:
        async with database.session_factory() as session:
            own = await service.append_record(session, data=_record_data(first), occurred_at=now)
            await service.append_record(session, data=_record_data(second), occurred_at=now)
            records = await service.list_recent_records(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                limit=1,
                action="task.update",
                resource_type="task",
                resource_id=first.task_id,
            )
            assert [record.id for record in records] == [own.id]
            with pytest.raises(ApplicationError):
                await service.list_recent_records(
                    session, tenant_id=first.tenant_id, workspace_id=first.workspace_id, limit=101
                )
    finally:
        await database.dispose()
