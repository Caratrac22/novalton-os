import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings
from novalton_api.core.database import Base, Database
from novalton_api.main import create_app
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID


@dataclass(frozen=True)
class ApiContext:
    client: TestClient
    first: Scope
    second_workspace: Scope
    second_tenant: Scope


async def _reset_and_seed() -> tuple[Scope, Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(AuditRecord))
            await session.execute(delete(RuntimeEvent))
            await session.execute(delete(Task))
            await session.execute(delete(Project))
            await session.execute(delete(Workspace))
            await session.execute(delete(Tenant))

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
            second_tenant_workspace = Workspace(
                tenant_id=second_tenant.id, name="Second workspace", slug="second"
            )
            session.add_all([first_workspace, other_workspace, second_tenant_workspace])
            await session.flush()
            return (
                Scope(first_tenant.id, first_workspace.id),
                Scope(first_tenant.id, other_workspace.id),
                Scope(second_tenant.id, second_tenant_workspace.id),
            )
    finally:
        await database.dispose()


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


@pytest.fixture
def api() -> Iterator[ApiContext]:
    first, second_workspace, second_tenant = asyncio.run(_reset_and_seed())
    with TestClient(create_app()) as client:
        yield ApiContext(client, first, second_workspace, second_tenant)
    asyncio.run(_reset())


def _collection(scope: Scope) -> str:
    return f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/projects"


def _project(scope: Scope, project_id: str | UUID) -> str:
    return f"{_collection(scope)}/{project_id}"


def _create(api: ApiContext, scope: Scope, *, slug: str = "alpha", name: str = "Alpha"):
    return api.client.post(
        _collection(scope),
        json={"name": name, "slug": slug, "description": "Private project details"},
    )


def test_project_metadata_has_workspace_scope_and_constraints() -> None:
    assert set(Base.metadata.tables) == {
        "approval_requests",
        "tenants",
        "workspaces",
        "projects",
        "tasks",
        "runtime_events",
        "audit_records",
        "policy_rules",
    }
    table = Base.metadata.tables["projects"]
    names = {constraint.name for constraint in table.constraints}
    assert table.c.id.primary_key
    assert not table.c.workspace_id.nullable
    assert {
        "fk_projects_workspace_id_workspaces",
        "uq_projects_workspace_id_slug",
        "ck_projects_description_length",
        "ck_projects_status_value",
    }.issubset(names)
    foreign_key = next(iter(table.c.workspace_id.foreign_keys))
    assert foreign_key.target_fullname == "workspaces.id"
    assert foreign_key.ondelete == "RESTRICT"


def test_create_list_read_update_delete_contract(api: ApiContext) -> None:
    created = _create(api, api.first)
    assert created.status_code == 201
    body = created.json()
    assert body["workspace_id"] == str(api.first.workspace_id)
    assert body["status"] == "ACTIVE"
    assert body["description"] == "Private project details"
    assert body["created_at"].endswith("Z") or "+00:00" in body["created_at"]

    listed = api.client.get(_collection(api.first), params={"limit": 1, "offset": 0})
    assert listed.status_code == 200
    assert listed.json()["limit"] == 1
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]

    read = api.client.get(_project(api.first, body["id"]))
    assert read.status_code == 200
    assert read.json() == body

    updated = api.client.patch(
        _project(api.first, body["id"]),
        json={"name": "Renamed", "description": None, "status": "PAUSED"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["description"] is None
    assert updated.json()["status"] == "PAUSED"

    deleted = api.client.delete(_project(api.first, body["id"]))
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api.client.get(_project(api.first, body["id"])).status_code == 404


def test_list_is_bounded_validated_and_deterministically_ordered(api: ApiContext) -> None:
    first = _create(api, api.first, slug="first", name="First").json()
    second = _create(api, api.first, slug="second", name="Second").json()

    response = api.client.get(_collection(api.first))
    assert response.status_code == 200
    assert response.json()["limit"] == 50
    assert [item["id"] for item in response.json()["items"]] == [first["id"], second["id"]]
    assert api.client.get(_collection(api.first), params={"limit": 101}).status_code == 422


def test_duplicate_slug_is_scoped_to_workspace_and_transaction_recovers(api: ApiContext) -> None:
    assert _create(api, api.first).status_code == 201
    second = _create(api, api.first, slug="second").json()
    duplicate = _create(api, api.first, name="Duplicate")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == {
        "code": "project_slug_conflict",
        "message": "A project with this slug already exists in the workspace",
    }
    assert "Private project details" not in duplicate.text
    assert _create(api, api.first, slug="after-conflict").status_code == 201
    duplicate_update = api.client.patch(_project(api.first, second["id"]), json={"slug": "alpha"})
    assert duplicate_update.status_code == 409
    recovered_update = api.client.patch(
        _project(api.first, second["id"]), json={"name": "Recovered"}
    )
    assert recovered_update.status_code == 200
    assert recovered_update.json()["slug"] == "second"
    assert _create(api, api.second_workspace).status_code == 201
    assert _create(api, api.second_tenant).status_code == 201
    assert len(api.client.get(_collection(api.second_workspace)).json()["items"]) == 1
    assert len(api.client.get(_collection(api.second_tenant)).json()["items"]) == 1


@pytest.mark.parametrize("operation", ["get", "patch", "delete"])
def test_cross_workspace_and_cross_tenant_project_access_is_not_found(
    api: ApiContext, operation: str
) -> None:
    project_id = _create(api, api.first).json()["id"]
    for wrong_scope in (api.second_workspace, api.second_tenant):
        if operation == "get":
            response = api.client.get(_project(wrong_scope, project_id))
        elif operation == "patch":
            response = api.client.patch(
                _project(wrong_scope, project_id), json={"name": "Must not update"}
            )
        else:
            response = api.client.delete(_project(wrong_scope, project_id))
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "resource_not_found",
            "message": "Resource not found",
        }


def test_workspace_must_belong_to_supplied_tenant(api: ApiContext) -> None:
    mismatched = Scope(api.second_tenant.tenant_id, api.first.workspace_id)
    response = _create(api, mismatched)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"


@pytest.mark.parametrize("kind", ["tenant", "workspace", "project"])
def test_unknown_scope_returns_same_not_found_envelope(api: ApiContext, kind: str) -> None:
    scope = api.first
    project_id = uuid4()
    if kind == "tenant":
        scope = Scope(uuid4(), scope.workspace_id)
    elif kind == "workspace":
        scope = Scope(scope.tenant_id, uuid4())
    response = api.client.get(_project(scope, project_id), headers={"X-Correlation-ID": "scope-x"})
    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"] == "scope-x"
    assert response.json() == {
        "error": {"code": "resource_not_found", "message": "Resource not found"},
        "correlation_id": "scope-x",
    }


def test_project_payload_validation_is_strict_and_sanitized(api: ApiContext) -> None:
    secret = "INVALID SECRET DESCRIPTION"
    response = api.client.post(
        _collection(api.first),
        json={"name": "Alpha", "slug": "Invalid Slug", "description": secret},
        headers={"X-Correlation-ID": "validation-x"},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "validation_error", "message": "Request validation failed"},
        "correlation_id": "validation-x",
    }
    assert secret not in response.text
    assert api.client.patch(_project(api.first, uuid4()), json={}).status_code == 422


@pytest.mark.asyncio
async def test_project_requires_existing_workspace_and_workspace_delete_is_restricted() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            session.add(
                Project(workspace_id=uuid4(), name="Orphan", slug="orphan", status="ACTIVE")
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Protected", slug=f"protected-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Protected", slug="protected")
            session.add(workspace)
            await session.flush()
            session.add(
                Project(
                    workspace_id=workspace.id,
                    name="Project",
                    slug="project",
                    status="ACTIVE",
                )
            )

        async with database.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await session.rollback()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_database_schema_matches_metadata() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        assert set(table_names) >= set(Base.metadata.tables)
    finally:
        await database.dispose()
