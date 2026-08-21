"""Explicit local tenant/workspace database bootstrap command."""

import asyncio
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.modules.agents.models import AgentDefinition
from novalton_api.modules.developer_manager.service import (
    DEVELOPER_MANAGER_CAPABILITIES,
    DEVELOPER_MANAGER_CATEGORY,
    DEVELOPER_MANAGER_MISSION,
    DEVELOPER_MANAGER_NAME,
    DEVELOPER_MANAGER_SLUG,
)
from novalton_api.modules.developer_worker.service import (
    DEVELOPER_WORKER_CAPABILITIES,
    DEVELOPER_WORKER_CATEGORY,
    DEVELOPER_WORKER_MISSION,
    DEVELOPER_WORKER_NAME,
    DEVELOPER_WORKER_SLUG,
)
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_slug


class BootstrapError(RuntimeError):
    """A deterministic bootstrap validation failure."""


@dataclass(frozen=True)
class BootstrapResult:
    """The deterministic local scope returned by bootstrap."""

    tenant: Tenant
    workspace: Workspace
    developer_manager: AgentDefinition
    developer_worker: AgentDefinition


async def _bootstrap_agent_definition(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    name: str,
    slug: str,
    category: str,
    mission: str,
    capabilities: list[str],
) -> AgentDefinition:
    definition = await session.scalar(
        select(AgentDefinition).where(
            AgentDefinition.tenant_id == tenant_id,
            AgentDefinition.workspace_id == workspace_id,
            AgentDefinition.slug == slug,
            AgentDefinition.version == 1,
        )
    )
    expected = (name, 1, "ENABLED", category, mission, capabilities, [])
    if definition is None:
        definition = AgentDefinition(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            version=1,
            status="ENABLED",
            category=category,
            mission=mission,
            capabilities=capabilities,
            permissions=[],
        )
        session.add(definition)
        await session.flush()
    actual = (
        definition.name,
        definition.version,
        definition.status,
        definition.category,
        definition.mission,
        definition.capabilities,
        definition.permissions,
    )
    if actual != expected:
        raise BootstrapError(f"{name} definition conflicts with existing data")
    return definition


async def bootstrap_local_scope(session: AsyncSession, settings: Settings) -> BootstrapResult:
    """Create or validate the configured local tenant and workspace."""
    if settings.environment == "production":
        raise BootstrapError("local bootstrap is disabled in production")

    await session.execute(
        insert(Tenant)
        .values(
            id=settings.bootstrap_tenant_id,
            name=settings.bootstrap_tenant_name,
            slug=settings.bootstrap_tenant_slug,
        )
        .on_conflict_do_nothing()
    )
    tenant = await session.scalar(select(Tenant).where(Tenant.id == settings.bootstrap_tenant_id))
    if tenant is None or (tenant.name, tenant.slug) != (
        settings.bootstrap_tenant_name,
        settings.bootstrap_tenant_slug,
    ):
        raise BootstrapError("configured bootstrap tenant conflicts with existing data")

    await session.execute(
        insert(Workspace)
        .values(
            id=settings.bootstrap_workspace_id,
            tenant_id=tenant.id,
            name=settings.bootstrap_workspace_name,
            slug=settings.bootstrap_workspace_slug,
        )
        .on_conflict_do_nothing()
    )
    workspace = await get_workspace_by_tenant_and_slug(
        session, tenant_id=tenant.id, slug=settings.bootstrap_workspace_slug
    )
    if workspace is None or (workspace.id, workspace.name) != (
        settings.bootstrap_workspace_id,
        settings.bootstrap_workspace_name,
    ):
        raise BootstrapError("configured bootstrap workspace conflicts with existing data")
    developer_manager = await _bootstrap_agent_definition(
        session,
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        name=DEVELOPER_MANAGER_NAME,
        slug=DEVELOPER_MANAGER_SLUG,
        category=DEVELOPER_MANAGER_CATEGORY,
        mission=DEVELOPER_MANAGER_MISSION,
        capabilities=DEVELOPER_MANAGER_CAPABILITIES,
    )
    developer_worker = await _bootstrap_agent_definition(
        session,
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        name=DEVELOPER_WORKER_NAME,
        slug=DEVELOPER_WORKER_SLUG,
        category=DEVELOPER_WORKER_CATEGORY,
        mission=DEVELOPER_WORKER_MISSION,
        capabilities=DEVELOPER_WORKER_CAPABILITIES,
    )
    return BootstrapResult(
        tenant=tenant,
        workspace=workspace,
        developer_manager=developer_manager,
        developer_worker=developer_worker,
    )


async def run_bootstrap() -> BootstrapResult:
    """Run bootstrap in one explicit transaction and close the engine."""
    settings = get_settings()
    database = Database.from_settings(settings)
    try:
        async with database.session_factory.begin() as session:
            return await bootstrap_local_scope(session, settings)
    finally:
        await database.dispose()


def main() -> int:
    """CLI entry point with sanitized deterministic failures."""
    try:
        result = asyncio.run(run_bootstrap())
    except BootstrapError as exc:
        print(f"Database bootstrap failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Database bootstrap failed: database operation unsuccessful", file=sys.stderr)
        return 1

    print(f"Database bootstrap complete: tenant={result.tenant.id} workspace={result.workspace.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
