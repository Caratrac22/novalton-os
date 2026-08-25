import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.agents import service
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionResponse,
    AgentDefinitionVersionCreate,
    AgentRunCreate,
)
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID


async def _seed() -> tuple[Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            scopes = []
            for marker in ("first", "second"):
                tenant = Tenant(name=marker, slug=f"agent-{marker}-{uuid4().hex[:6]}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(tenant_id=tenant.id, name=marker, slug=marker)
                session.add(workspace)
                await session.flush()
                project = Project(workspace_id=workspace.id, name=marker, slug=marker)
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title=marker)
                session.add(task)
                await session.flush()
                scopes.append(Scope(tenant.id, workspace.id, project.id, task.id))
            return scopes[0], scopes[1]
    finally:
        await database.dispose()


async def _cleanup(scopes: tuple[Scope, Scope]) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            ids = [scope.tenant_id for scope in scopes]
            await session.execute(
                update(AgentRun).where(AgentRun.tenant_id.in_(ids)).values(model_run_id=None)
            )
            await session.execute(delete(ModelRun).where(ModelRun.tenant_id.in_(ids)))
            await session.execute(delete(AgentRun).where(AgentRun.tenant_id.in_(ids)))
            await session.execute(delete(AgentDefinition).where(AgentDefinition.tenant_id.in_(ids)))
            await session.execute(delete(AuditRecord).where(AuditRecord.tenant_id.in_(ids)))
            for scope in scopes:
                await session.execute(delete(Task).where(Task.id == scope.task_id))
                await session.execute(delete(Project).where(Project.id == scope.project_id))
                await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
                await session.execute(delete(Tenant).where(Tenant.id == scope.tenant_id))
    finally:
        await database.dispose()


@pytest.fixture
def scopes() -> tuple[Scope, Scope]:
    value = asyncio.run(_seed())
    yield value
    asyncio.run(_cleanup(value))


def _definition(**changes: object) -> AgentDefinitionCreate:
    values: dict[str, object] = {
        "name": "Developer",
        "slug": "developer",
        "mission": "Build approved software safely.",
        "capabilities": ["testing", "python", "python"],
        "permissions": ["repository_read"],
    }
    values.update(changes)
    return AgentDefinitionCreate(**values)


async def _create(scope: Scope, **changes: object) -> AgentDefinition:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            return await service.create_definition(
                session,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data=_definition(**changes),
            )
    finally:
        await database.dispose()


def test_capabilities_are_bounded_normalized_and_no_contract_payloads() -> None:
    data = _definition(capabilities=["testing", "python", "testing"])
    assert data.capabilities == ["python", "testing"]
    with pytest.raises(ValidationError):
        _definition(capabilities=[f"cap_{index}" for index in range(33)])
    assert "input_json" not in AgentRun.__table__.c
    assert "result_json" not in AgentRun.__table__.c
    assert "provider_id" not in AgentDefinition.__table__.c


def test_versioning_preserves_prior_run_snapshot_and_lifecycle(scopes: tuple[Scope, Scope]) -> None:
    first, _ = scopes
    definition = asyncio.run(_create(first))

    async def scenario() -> tuple[AgentRun, AgentDefinition, AgentRun]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                run = await service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=AgentRunCreate(
                        agent_definition_id=definition.id,
                        project_id=first.project_id,
                        task_id=first.task_id,
                    ),
                )
                run = await service.start_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                )
                run = await service.succeed_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                )
                version = await service.create_version(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    definition_id=definition.id,
                    data=AgentDefinitionVersionCreate(
                        name="Developer v2",
                        mission="Review approved software.",
                        capabilities=["code_review"],
                        permissions=[],
                    ),
                )
                stored = await service.get_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    run_id=run.id,
                )
                return run, version, stored
        finally:
            await database.dispose()

    run, version, stored = asyncio.run(scenario())
    assert (run.status, run.started_at is not None, run.completed_at is not None) == (
        "SUCCEEDED",
        True,
        True,
    )
    assert (version.version, stored.agent_version, stored.agent_name) == (2, 1, "Developer")

    async def reopen() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError) as error:
                    await service.start_run(
                        session,
                        tenant_id=first.tenant_id,
                        workspace_id=first.workspace_id,
                        run_id=run.id,
                    )
                assert error.value.code == "agent_run_invalid_transition"
        finally:
            await database.dispose()

    asyncio.run(reopen())


def test_scope_mismatches_are_sanitized_and_creation_has_no_side_effects(
    scopes: tuple[Scope, Scope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = scopes
    definition = asyncio.run(_create(first))
    provider = monkeypatch.setattr(
        "novalton_api.modules.model_router.service.simulate",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("router called")),
    )
    assert provider is None

    async def scenario() -> tuple[int, int]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError) as error:
                    await service.create_run(
                        session,
                        tenant_id=second.tenant_id,
                        workspace_id=second.workspace_id,
                        data=AgentRunCreate(
                            agent_definition_id=definition.id,
                            project_id=second.project_id,
                            task_id=second.task_id,
                        ),
                    )
                assert (error.value.code, error.value.message) == (
                    "resource_not_found",
                    "Resource not found",
                )
                await service.create_run(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=AgentRunCreate(
                        agent_definition_id=definition.id,
                        project_id=first.project_id,
                        task_id=first.task_id,
                    ),
                )
                return (
                    await session.scalar(select(func.count()).select_from(ModelRun)),
                    await session.scalar(select(func.count()).select_from(RuntimeEvent)),
                )
        finally:
            await database.dispose()

    assert asyncio.run(scenario()) == (0, 0)


def test_scoped_definition_and_run_read_apis(scopes: tuple[Scope, Scope]) -> None:
    first, second = scopes
    definition = asyncio.run(_create(first))

    async def direct_list() -> list[AgentDefinition]:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                return await service.list_definitions(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    limit=50,
                    offset=0,
                    all_versions=False,
                )
        finally:
            await database.dispose()

    direct_items = asyncio.run(direct_list())
    assert [item.id for item in direct_items] == [definition.id]
    AgentDefinitionResponse.model_validate(direct_items[0])
    with TestClient(create_app()) as client:
        base = f"/api/v1/tenants/{first.tenant_id}/workspaces/{first.workspace_id}"
        response = client.get(f"{base}/agents")
        assert response.status_code == 200
        assert response.json()["items"][0]["id"] == str(definition.id)
        foreign = client.get(
            f"/api/v1/tenants/{second.tenant_id}/workspaces/{second.workspace_id}/agents/{definition.id}"
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"] == {
            "code": "resource_not_found",
            "message": "Resource not found",
        }
        assert client.get(f"{base}/agent-runs", params={"limit": 101}).status_code == 422
