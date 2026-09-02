import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import func, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.modules.agents import repository as agents_repository
from novalton_api.modules.agents import service as agents_service
from novalton_api.modules.agents.models import AgentDefinition, AgentRun
from novalton_api.modules.agents.schemas import AgentRunCreate
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


def test_alembic_configuration_loads_i041_safe_review_summary() -> None:
    api_root = Path(__file__).parents[1]
    config = Config(api_root / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)

    head = scripts.get_current_head()
    revision = scripts.get_revision(head)
    baseline = scripts.get_revision("20260820_0001")

    assert head == "20260901_0029"
    assert revision is not None
    assert revision.down_revision == "20260831_0028"
    assert baseline is not None
    assert baseline.down_revision is None


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
