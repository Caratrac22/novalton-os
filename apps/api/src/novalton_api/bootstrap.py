"""Explicit local tenant/workspace database bootstrap command."""

import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
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
    return BootstrapResult(tenant=tenant, workspace=workspace)


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
