from datetime import UTC
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.bootstrap import BootstrapError, bootstrap_local_scope
from novalton_api.core.config import Settings
from novalton_api.core.database import Base, Database
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_slug


@pytest_asyncio.fixture
async def database() -> Database:
    value = Database.from_settings(Settings())
    async with value.engine.begin() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )
    if not {"tenants", "workspaces"}.issubset(table_names):
        await value.dispose()
        pytest.fail("PostgreSQL must be migrated to the I-005 head before integration tests")

    async with value.session_factory.begin() as session:
        await session.execute(delete(RuntimeEvent))
        await session.execute(delete(Task))
        await session.execute(delete(Project))
        await session.execute(delete(Workspace))
        await session.execute(delete(Tenant))
    yield value
    async with value.session_factory.begin() as session:
        await session.execute(delete(RuntimeEvent))
        await session.execute(delete(Task))
        await session.execute(delete(Project))
        await session.execute(delete(Workspace))
        await session.execute(delete(Tenant))
    await value.dispose()


@pytest_asyncio.fixture
async def session(database: Database) -> AsyncSession:
    async with database.session_factory() as value:
        yield value
        await value.rollback()


def test_model_metadata_retains_i005_tables_and_constraints() -> None:
    assert {"tenants", "workspaces"}.issubset(Base.metadata.tables)
    tenants = Base.metadata.tables["tenants"]
    workspaces = Base.metadata.tables["workspaces"]

    assert tenants.c.id.primary_key
    assert workspaces.c.id.primary_key
    assert not workspaces.c.tenant_id.nullable
    assert {constraint.name for constraint in tenants.constraints} >= {"uq_tenants_slug"}
    assert {constraint.name for constraint in workspaces.constraints} >= {
        "fk_workspaces_tenant_id_tenants",
        "uq_workspaces_tenant_id_slug",
    }
    foreign_key = next(iter(workspaces.c.tenant_id.foreign_keys))
    assert foreign_key.target_fullname == "tenants.id"
    assert foreign_key.ondelete == "RESTRICT"


@pytest.mark.asyncio
async def test_workspace_slug_is_unique_only_within_tenant(session: AsyncSession) -> None:
    first_tenant = Tenant(name="First", slug="first")
    second_tenant = Tenant(name="Second", slug="second")
    session.add_all([first_tenant, second_tenant])
    await session.flush()
    session.add_all(
        [
            Workspace(tenant_id=first_tenant.id, name="Default", slug="default"),
            Workspace(tenant_id=second_tenant.id, name="Default", slug="default"),
        ]
    )
    await session.flush()
    session.add(Workspace(tenant_id=first_tenant.id, name="Duplicate", slug="default"))

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_workspace_requires_existing_tenant(session: AsyncSession) -> None:
    session.add(Workspace(tenant_id=uuid4(), name="Orphan", slug="orphan"))

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_tenant_delete_is_restricted_while_workspace_exists(
    session: AsyncSession,
) -> None:
    tenant = Tenant(name="Protected", slug="protected")
    session.add(tenant)
    await session.flush()
    session.add(Workspace(tenant_id=tenant.id, name="Default", slug="default"))
    await session.flush()

    with pytest.raises(IntegrityError):
        await session.execute(delete(Tenant).where(Tenant.id == tenant.id))


@pytest.mark.asyncio
async def test_workspace_lookup_is_tenant_scoped(session: AsyncSession) -> None:
    first_tenant = Tenant(name="First", slug="first")
    second_tenant = Tenant(name="Second", slug="second")
    session.add_all([first_tenant, second_tenant])
    await session.flush()
    first_workspace = Workspace(tenant_id=first_tenant.id, name="Default", slug="default")
    second_workspace = Workspace(tenant_id=second_tenant.id, name="Default", slug="default")
    session.add_all([first_workspace, second_workspace])
    await session.flush()

    result = await get_workspace_by_tenant_and_slug(
        session, tenant_id=second_tenant.id, slug="default"
    )

    assert result is second_workspace
    assert result is not first_workspace


@pytest.mark.asyncio
async def test_bootstrap_creates_expected_utc_timestamped_scope(database: Database) -> None:
    settings = Settings(environment="test")
    async with database.session_factory.begin() as session:
        result = await bootstrap_local_scope(session, settings)

    assert result.tenant.id == settings.bootstrap_tenant_id
    assert result.workspace.id == settings.bootstrap_workspace_id
    assert result.workspace.tenant_id == result.tenant.id
    assert result.tenant.created_at.tzinfo is not None
    assert result.tenant.created_at.astimezone(UTC).utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(database: Database) -> None:
    settings = Settings(environment="test")
    async with database.session_factory.begin() as session:
        first = await bootstrap_local_scope(session, settings)
    async with database.session_factory.begin() as session:
        second = await bootstrap_local_scope(session, settings)
        tenant_count = await session.scalar(select(func.count()).select_from(Tenant))
        workspace_count = await session.scalar(select(func.count()).select_from(Workspace))

    assert second.tenant.id == first.tenant.id
    assert second.workspace.id == first.workspace.id
    assert tenant_count == 1
    assert workspace_count == 1


@pytest.mark.asyncio
async def test_bootstrap_conflict_rolls_back_transaction(database: Database) -> None:
    settings = Settings(environment="test")
    async with database.session_factory.begin() as session:
        session.add(
            Tenant(
                id=settings.bootstrap_tenant_id,
                name="Conflicting Name",
                slug=settings.bootstrap_tenant_slug,
            )
        )

    with pytest.raises(BootstrapError, match="configured bootstrap tenant conflicts"):
        async with database.session_factory.begin() as session:
            await bootstrap_local_scope(session, settings)

    async with database.session_factory() as session:
        workspace_count = await session.scalar(select(func.count()).select_from(Workspace))
    assert workspace_count == 0


@pytest.mark.asyncio
async def test_bootstrap_is_disabled_in_production(session: AsyncSession) -> None:
    with pytest.raises(BootstrapError, match="disabled in production"):
        await bootstrap_local_scope(session, Settings(environment="production"))
