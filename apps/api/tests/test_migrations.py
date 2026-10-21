import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, select, text

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.modules.agents import repository as agents_repository
from novalton_api.modules.agents import service as agents_service
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import AgentRunCreate
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


def test_alembic_configuration_loads_durable_dispatch_after_i044() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    head = scripts.get_current_head()
    revision = scripts.get_revision(head)
    predecessor = scripts.get_revision("20260902_0031")

    assert head == "20261021_0039"
    assert revision is not None
    assert revision.down_revision == "20261021_0038"
    assert scripts.get_revision("20261021_0038").down_revision == "20261021_0037"
    assert scripts.get_revision("20261021_0037").down_revision == "20261021_0036"
    assert scripts.get_revision("20261021_0036").down_revision == "20261021_0035"
    assert scripts.get_revision("20261021_0035").down_revision == "20261020_0034"
    assert scripts.get_revision("20261020_0034").down_revision == "20261020_0033"
    assert scripts.get_revision("20261020_0033").down_revision == "20261011_0032"
    assert scripts.get_revision("20261011_0032").down_revision == "20260902_0031"
    assert predecessor is not None
    assert predecessor.down_revision == "20260902_0030"


def test_postgres_migration_downgrades_to_i023_and_reupgrades() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")

    command.upgrade(config, "head")
    try:
        command.downgrade(config, "20260820_0012")
    finally:
        command.upgrade(config, "head")


def test_i041_developer_v3_downgrade_retains_historical_agent_run_and_reupgrades() -> None:
    """The v3 definition is archived on downgrade, never deleted beneath historical runs."""
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")
    command.downgrade(config, "20260831_0027")

    async def seed_v2_and_run() -> tuple[UUID, UUID, UUID, UUID]:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                tenant = Tenant(name="I041 migration", slug=f"i041-migration-{uuid4().hex[:12]}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(tenant_id=tenant.id, name="I041 migration", slug="i041")
                session.add(workspace)
                await session.flush()
                project = Project(workspace_id=workspace.id, name="I041 migration", slug="i041")
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title="Retain immutable definition")
                definition = AgentDefinition(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    name="Developer Worker",
                    slug="developer_worker",
                    version=2,
                    status="ENABLED",
                    category="development",
                    mission="Execute a bounded development assignment.",
                    capabilities=["code_reasoning"],
                    permissions=["workspace.read_file"],
                )
                session.add_all([task, definition])
                await session.commit()
                return tenant.id, workspace.id, project.id, task.id
        finally:
            await database.dispose()

    tenant_id, workspace_id, project_id, task_id = asyncio.run(seed_v2_and_run())
    try:
        command.upgrade(config, "20260831_0028")

        async def create_and_verify_v3_run() -> tuple[UUID, UUID]:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    current = await agents_repository.latest_definition(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        slug="developer_worker",
                        exclude_archived=True,
                    )
                    assert current is not None and current.version == 3
                    run = await agents_service.create_run(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        data=AgentRunCreate(
                            agent_definition_id=current.id,
                            project_id=project_id,
                            task_id=task_id,
                        ),
                    )
                    return current.id, run.id
            finally:
                await database.dispose()

        v3_id, run_id = asyncio.run(create_and_verify_v3_run())
        command.downgrade(config, "20260831_0027")

        async def verify_downgrade() -> None:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    run = await session.get(AgentRun, run_id)
                    retained = await session.get(AgentDefinition, v3_id)
                    current = await agents_repository.latest_definition(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        slug="developer_worker",
                        exclude_archived=True,
                    )
                    assert run is not None and run.agent_definition_id == v3_id
                    assert retained is not None and retained.status == "ARCHIVED"
                    assert current is not None and current.version == 2
            finally:
                await database.dispose()

        asyncio.run(verify_downgrade())
        command.upgrade(config, "20260831_0028")

        async def verify_reupgrade() -> None:
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    run = await session.get(AgentRun, run_id)
                    current = await agents_repository.latest_definition(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        slug="developer_worker",
                        exclude_archived=True,
                    )
                    v3_count = await session.scalar(
                        select(func.count())
                        .select_from(AgentDefinition)
                        .where(
                            AgentDefinition.tenant_id == tenant_id,
                            AgentDefinition.workspace_id == workspace_id,
                            AgentDefinition.slug == "developer_worker",
                            AgentDefinition.version == 3,
                        )
                    )
                    assert run is not None and run.agent_definition_id == v3_id
                    assert current is not None and current.id == v3_id and current.version == 3
                    assert v3_count == 1
            finally:
                await database.dispose()

        asyncio.run(verify_reupgrade())
    finally:
        command.upgrade(config, "head")


def test_i044_immutable_verification_authority_round_trip():
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    command.downgrade(config, "20260902_0031")

    async def seed():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory.begin() as session:
                tenant = Tenant(name="I044 migration", slug=f"i044-{uuid4().hex[:12]}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(tenant_id=tenant.id, name="I044 migration", slug="i044")
                session.add(workspace)
                await session.flush()
                old = AgentDefinition(
                    tenant_id=tenant.id,
                    workspace_id=workspace.id,
                    name="Developer Worker",
                    slug="developer_worker",
                    version=3,
                    status="ENABLED",
                    category="development",
                    mission="Retain immutable authority",
                    capabilities=["code_reasoning"],
                    permissions=[
                        "workspace.list_files",
                        "workspace.read_file",
                        "workspace.search_text",
                        "workspace.replace_text",
                    ],
                )
                session.add(old)
                await session.flush()
                return tenant.id, workspace.id, old.id
        finally:
            await database.dispose()

    tenant_id, workspace_id, old_id = asyncio.run(seed())

    async def inspect_index(expected_columns: str) -> None:
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                definition = await session.scalar(
                    text(
                        "SELECT pg_get_indexdef('uq_model_runs_agent_tool_continuation'::regclass)"
                    )
                )
                assert definition is not None
                assert f"({expected_columns})" in definition
                assert "recovery_attempt_kind" in definition
                assert "TOOL_CONTINUATION" in definition
        finally:
            await database.dispose()

    async def inspect(expected_status, historical_run=None):
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                old = await session.get(AgentDefinition, old_id)
                assert old.permissions == [
                    "workspace.list_files",
                    "workspace.read_file",
                    "workspace.search_text",
                    "workspace.replace_text",
                ]
                current = await session.scalar(
                    select(AgentDefinition).where(
                        AgentDefinition.tenant_id == tenant_id,
                        AgentDefinition.workspace_id == workspace_id,
                        AgentDefinition.slug == "developer_worker",
                        AgentDefinition.version == 4,
                    )
                )
                assert current.status == expected_status
                assert current.permissions == [
                    "workspace.list_files",
                    "workspace.read_file",
                    "workspace.search_text",
                    "workspace.replace_text",
                    "verify.backend_syntax",
                ]
                if historical_run is None:
                    run = await agents_service.create_run(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        data=AgentRunCreate(agent_definition_id=current.id),
                    )
                    return run.id, current.id
                run = await session.get(AgentRun, historical_run[0])
                assert run.agent_definition_id == current.id == historical_run[1]
        finally:
            await database.dispose()

    try:
        asyncio.run(inspect_index("agent_run_id"))
        command.upgrade(config, "head")
        asyncio.run(inspect_index("agent_run_id, recovery_attempt_index"))
        retained = asyncio.run(inspect("ENABLED"))
        command.downgrade(config, "20260902_0031")
        asyncio.run(inspect_index("agent_run_id"))
        asyncio.run(inspect("ARCHIVED", retained))
        command.upgrade(config, "head")
        asyncio.run(inspect_index("agent_run_id, recovery_attempt_index"))
        asyncio.run(inspect("ENABLED", retained))
    finally:
        command.upgrade(config, "head")


def test_durable_dispatch_downgrade_preserves_enqueued_history(monkeypatch):
    from test_development_workflow import QueueProvider, _cleanup, _create_vertical, _seed
    from test_durable_dispatch import cleanup_operator, configure_operator, operator_for

    from novalton_api.modules.durable_dispatch import service as dispatch_service
    from novalton_api.modules.durable_dispatch.models import DispatchActivation, TaskDispatch
    from novalton_api.modules.durable_dispatch.schemas import DispatchRequest

    config = Config(Path(__file__).parents[1] / "alembic.ini")
    value = asyncio.run(_seed())
    configure_operator(value, monkeypatch)
    provider = QueueProvider([])
    body, _ = _create_vertical(value, provider)

    async def enqueue():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                await dispatch_service.configure_workspace(
                    session,
                    operator=operator_for(value),
                    tenant_id=value.tenant_id,
                    workspace_id=value.workspace_id,
                    enabled=False,
                )
                row = await dispatch_service.enqueue(
                    session,
                    operator=operator_for(value),
                    tenant_id=value.tenant_id,
                    workspace_id=value.workspace_id,
                    data=DispatchRequest(
                        workflow_run_id=UUID(body["workflow_run"]["id"]),
                        request_key="migration-evidence",
                        deadline=datetime.now(UTC) + timedelta(hours=1),
                    ),
                )
                return row.id
        finally:
            await database.dispose()

    identifier = asyncio.run(enqueue())
    try:
        with pytest.raises(RuntimeError, match="operator_membership_downgrade_has_history"):
            command.downgrade(config, "20261011_0032")

        async def preserved():
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    assert await session.get(TaskDispatch, identifier) is not None
                    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
                    # Alembic rolls the whole downgrade command back when the
                    # membership history guard rejects it.
                    assert revision == "20261021_0039"
            finally:
                await database.dispose()

        asyncio.run(preserved())
    finally:

        async def cleanup():
            database = Database.from_settings(Settings.from_environment())
            try:
                async with database.session_factory() as session:
                    await session.execute(delete(TaskDispatch).where(TaskDispatch.id == identifier))
                    await session.execute(
                        delete(DispatchActivation).where(
                            DispatchActivation.tenant_id == value.tenant_id
                        )
                    )
                    await session.commit()
            finally:
                await database.dispose()

        asyncio.run(cleanup())
        cleanup_operator(value)
        asyncio.run(_cleanup(value))
        command.downgrade(config, "20261011_0032")
        command.upgrade(config, "head")
        get_settings.cache_clear()
