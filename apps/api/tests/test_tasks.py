import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings
from novalton_api.core.database import Base, Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks import service as task_service
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tasks.schemas import TaskCreate
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class ProjectScope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID


@dataclass(frozen=True)
class ApiContext:
    client: TestClient
    first: ProjectScope
    second_project: ProjectScope
    second_workspace: ProjectScope
    second_tenant: ProjectScope


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


async def _seed() -> tuple[ProjectScope, ProjectScope, ProjectScope, ProjectScope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            first_tenant = Tenant(name="First tenant", slug=f"first-{uuid4().hex[:8]}")
            second_tenant = Tenant(name="Second tenant", slug=f"second-{uuid4().hex[:8]}")
            session.add_all([first_tenant, second_tenant])
            await session.flush()
            first_workspace = Workspace(
                tenant_id=first_tenant.id, name="First workspace", slug="first"
            )
            other_workspace = Workspace(
                tenant_id=first_tenant.id, name="Other workspace", slug="other"
            )
            tenant_two_workspace = Workspace(
                tenant_id=second_tenant.id, name="Second workspace", slug="second"
            )
            session.add_all([first_workspace, other_workspace, tenant_two_workspace])
            await session.flush()
            first_project = Project(
                workspace_id=first_workspace.id, name="First", slug="first", status="ACTIVE"
            )
            sibling_project = Project(
                workspace_id=first_workspace.id, name="Sibling", slug="sibling", status="ACTIVE"
            )
            other_project = Project(
                workspace_id=other_workspace.id, name="Other", slug="other", status="ACTIVE"
            )
            tenant_two_project = Project(
                workspace_id=tenant_two_workspace.id,
                name="Second tenant",
                slug="second",
                status="ACTIVE",
            )
            session.add_all([first_project, sibling_project, other_project, tenant_two_project])
            await session.flush()
            return (
                ProjectScope(first_tenant.id, first_workspace.id, first_project.id),
                ProjectScope(first_tenant.id, first_workspace.id, sibling_project.id),
                ProjectScope(first_tenant.id, other_workspace.id, other_project.id),
                ProjectScope(second_tenant.id, tenant_two_workspace.id, tenant_two_project.id),
            )
    finally:
        await database.dispose()


@pytest.fixture
def api() -> Iterator[ApiContext]:
    asyncio.run(_reset())
    scopes = asyncio.run(_seed())
    with TestClient(create_app()) as client:
        yield ApiContext(client, *scopes)
    asyncio.run(_reset())


def _collection(scope: ProjectScope) -> str:
    return (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/projects/{scope.project_id}/tasks"
    )


def _task(scope: ProjectScope, task_id: str | UUID) -> str:
    return f"{_collection(scope)}/{task_id}"


def _create(api: ApiContext, scope: ProjectScope, *, title: str = "First task", **extra):
    return api.client.post(_collection(scope), json={"title": title, **extra})


def test_task_metadata_has_project_scope_and_constraints() -> None:
    table = Base.metadata.tables["tasks"]
    names = {constraint.name for constraint in table.constraints}
    assert table.c.id.primary_key
    assert not table.c.project_id.nullable
    assert {
        "fk_tasks_project_id_projects",
        "ck_tasks_title_length",
        "ck_tasks_description_length",
        "ck_tasks_status_value",
    }.issubset(names)
    foreign_key = next(iter(table.c.project_id.foreign_keys))
    assert foreign_key.target_fullname == "projects.id"
    assert foreign_key.ondelete == "CASCADE"
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True


def test_create_list_read_update_delete_contract(api: ApiContext) -> None:
    created = _create(api, api.first, description="Private task details")
    assert created.status_code == 201
    body = created.json()
    assert body["project_id"] == str(api.first.project_id)
    assert body["status"] == "BACKLOG"
    assert body["description"] == "Private task details"
    assert body["created_at"].endswith("Z") or "+00:00" in body["created_at"]

    listed = api.client.get(_collection(api.first), params={"limit": 1, "offset": 0})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]

    assert api.client.get(_task(api.first, body["id"])).json() == body
    updated = api.client.patch(
        _task(api.first, body["id"]),
        json={"title": "Renamed", "description": None, "status": "IN_PROGRESS"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed"
    assert updated.json()["description"] is None
    assert updated.json()["status"] == "IN_PROGRESS"

    deleted = api.client.delete(_task(api.first, body["id"]))
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api.client.get(_task(api.first, body["id"])).status_code == 404


def test_all_documented_states_are_accepted_without_transition_rules(api: ApiContext) -> None:
    task_id = _create(api, api.first).json()["id"]
    states = ["BACKLOG", "READY", "IN_PROGRESS", "BLOCKED", "REVIEW", "DONE", "CANCELLED"]
    for state in states:
        response = api.client.patch(_task(api.first, task_id), json={"status": state})
        assert response.status_code == 200
        assert response.json()["status"] == state

    invalid = api.client.patch(_task(api.first, task_id), json={"status": "RUNNING"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_list_is_bounded_ordered_offset_and_status_filtered(api: ApiContext) -> None:
    first = _create(api, api.first, title="First", status="READY").json()
    second = _create(api, api.first, title="Second", status="DONE").json()
    third = _create(api, api.first, title="Third", status="READY").json()

    response = api.client.get(_collection(api.first))
    assert [item["id"] for item in response.json()["items"]] == [
        first["id"],
        second["id"],
        third["id"],
    ]
    paged = api.client.get(_collection(api.first), params={"limit": 1, "offset": 1})
    assert [item["id"] for item in paged.json()["items"]] == [second["id"]]
    filtered = api.client.get(_collection(api.first), params={"status": "READY"})
    assert [item["id"] for item in filtered.json()["items"]] == [first["id"], third["id"]]
    assert api.client.get(_collection(api.first), params={"limit": 101}).status_code == 422
    assert api.client.get(_collection(api.first), params={"status": "RUNNING"}).status_code == 422


@pytest.mark.parametrize("operation", ["get", "patch", "delete"])
def test_task_id_never_bypasses_project_or_parent_scope(api: ApiContext, operation: str) -> None:
    task_id = _create(api, api.first).json()["id"]
    scopes = [api.second_project, api.second_workspace, api.second_tenant]
    scopes.append(ProjectScope(uuid4(), api.first.workspace_id, api.first.project_id))
    scopes.append(ProjectScope(api.first.tenant_id, uuid4(), api.first.project_id))
    scopes.append(ProjectScope(api.first.tenant_id, api.first.workspace_id, uuid4()))
    for scope in scopes:
        if operation == "get":
            response = api.client.get(_task(scope, task_id))
        elif operation == "patch":
            response = api.client.patch(_task(scope, task_id), json={"title": "Hidden"})
        else:
            response = api.client.delete(_task(scope, task_id))
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "resource_not_found",
            "message": "Resource not found",
        }


def test_unknown_task_has_correlation_id_and_safe_error(api: ApiContext) -> None:
    response = api.client.get(
        _task(api.first, uuid4()), headers={"X-Correlation-ID": "task-scope-x"}
    )
    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == "task-scope-x"
    assert response.json() == {
        "error": {"code": "resource_not_found", "message": "Resource not found"},
        "correlation_id": "task-scope-x",
    }


def test_task_payload_is_strict_bounded_and_sanitized(api: ApiContext) -> None:
    secret = "PRIVATE TASK DESCRIPTION"
    response = api.client.post(
        _collection(api.first),
        json={"title": "", "description": secret},
        headers={"X-Correlation-ID": "task-validation-x"},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "message": "Request validation failed"},
        "correlation_id": "task-validation-x",
    }
    assert secret not in response.text
    assert _create(api, api.first, description="x" * 4001).status_code == 422
    assert api.client.patch(_task(api.first, uuid4()), json={}).status_code == 422


@pytest.mark.asyncio
async def test_task_requires_project_and_project_delete_cascades() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            session.add(Task(project_id=uuid4(), title="Orphan", status="BACKLOG"))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Cascade", slug=f"cascade-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Cascade", slug="cascade")
            session.add(workspace)
            await session.flush()
            project = Project(
                workspace_id=workspace.id, name="Cascade", slug="cascade", status="ACTIVE"
            )
            session.add(project)
            await session.flush()
            task = Task(project_id=project.id, title="Cascade", status="BACKLOG")
            session.add(task)
            await session.flush()
            task_id = task.id
            await session.execute(delete(Project).where(Project.id == project.id))

        async with database.session_factory() as session:
            assert await session.get(Task, task_id) is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failed_task_create_rolls_back_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    monkeypatch.setattr(task_service, "_require_scope", AsyncMock())
    monkeypatch.setattr(
        task_service.repository,
        "create_task",
        AsyncMock(side_effect=IntegrityError("statement", {}, Exception("database failure"))),
    )

    with pytest.raises(ApplicationError) as error:
        await task_service.create_task(
            session,
            tenant_id=uuid4(),
            workspace_id=uuid4(),
            project_id=uuid4(),
            data=TaskCreate(title="Rollback"),
        )

    assert getattr(error.value, "code", None) == "resource_not_found"
    session.rollback.assert_awaited_once()
