"""Privileged one-time local CLI; no HTTP bootstrap or default password."""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database, verify_database_identity
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    TenantOperatorMembership,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.local_auth.models import LocalCredential, LocalSession
from novalton_api.modules.local_auth.service import hash_password, normalize_login
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


class BootstrapDenied(Exception):
    """One-time provisioning cannot proceed."""


async def bootstrap_owner(
    session: AsyncSession, *, settings: Settings, login: str, password: str
) -> HumanOperator:
    normalized, encoded = normalize_login(login), hash_password(password)
    # Serialized across processes, including when no owner row exists yet.
    await session.execute(text("SELECT pg_advisory_xact_lock(1314276940)"))
    if (
        await session.scalar(select(LocalCredential.user_id).limit(1)) is not None
        or await session.scalar(
            select(TenantOperatorMembership.user_id)
            .where(TenantOperatorMembership.role == "OWNER")
            .limit(1)
        )
        is not None
    ):
        raise BootstrapDenied("An identity already exists; use a reviewed recovery procedure")
    await session.execute(
        insert(Tenant)
        .values(
            id=settings.bootstrap_tenant_id,
            name=settings.bootstrap_tenant_name,
            slug=settings.bootstrap_tenant_slug,
        )
        .on_conflict_do_nothing()
    )
    tenant = await session.get(Tenant, settings.bootstrap_tenant_id)
    if tenant is None or (tenant.name, tenant.slug) != (
        settings.bootstrap_tenant_name,
        settings.bootstrap_tenant_slug,
    ):
        raise BootstrapDenied("Configured tenant conflicts with existing data")
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
    workspace = await session.get(Workspace, settings.bootstrap_workspace_id)
    if workspace is None or (workspace.tenant_id, workspace.name, workspace.slug) != (
        tenant.id,
        settings.bootstrap_workspace_name,
        settings.bootstrap_workspace_slug,
    ):
        raise BootstrapDenied("Configured workspace conflicts with existing data")
    user = HumanOperator(label=normalized, active=True)
    session.add(user)
    await session.flush()
    session.add(
        LocalCredential(
            user_id=user.id, login=normalized, password_hash=encoded, changed_at=datetime.now(UTC)
        )
    )
    session.add(
        TenantOperatorMembership(user_id=user.id, tenant_id=tenant.id, role="OWNER", active=True)
    )
    for permission in ("workspace.read", "workspace.write"):
        session.add(
            WorkspaceOperatorPermission(
                user_id=user.id,
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                permission=permission,
                active=True,
            )
        )
    await session.flush()
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            action="account.bootstrap.owner",
            actor_type="local_user",
            actor_id=str(user.id),
            outcome="success",
        ),
        commit=False,
    )
    return user


async def run_bootstrap(login: str, password: str) -> None:
    settings = get_settings()
    await verify_database_identity(settings)
    db = Database.from_settings(settings)
    try:
        async with db.session_factory.begin() as session:
            await bootstrap_owner(session, settings=settings, login=login, password=password)
    finally:
        await db.dispose()


async def recover_owner(
    session: AsyncSession, *, settings: Settings, login: str, password: str
) -> None:
    """Host-authorized recovery; retains every existing membership and grant."""
    normalized, encoded = normalize_login(login), hash_password(password)
    await session.execute(text("SELECT pg_advisory_xact_lock(1314276940)"))
    credential = await session.scalar(
        select(LocalCredential).where(LocalCredential.login == normalized).with_for_update()
    )
    if credential is None:
        raise BootstrapDenied("Local account unavailable")
    membership = await session.scalar(
        select(TenantOperatorMembership)
        .where(
            TenantOperatorMembership.user_id == credential.user_id,
            TenantOperatorMembership.tenant_id == settings.bootstrap_tenant_id,
            TenantOperatorMembership.role == "OWNER",
            TenantOperatorMembership.active.is_(True),
        )
        .with_for_update()
    )
    if membership is None:
        raise BootstrapDenied("Local owner unavailable for configured tenant")
    now = datetime.now(UTC)
    credential.password_hash, credential.changed_at = encoded, now
    await session.execute(
        update(LocalSession)
        .where(LocalSession.user_id == credential.user_id, LocalSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=settings.bootstrap_tenant_id,
            workspace_id=settings.bootstrap_workspace_id,
            action="account.password.recover",
            actor_type="service",
            actor_id=str(credential.user_id),
            outcome="success",
            metadata={"authority": "privileged_host_cli"},
        ),
        commit=False,
    )


async def run_recovery(login: str, password: str) -> None:
    settings = get_settings()
    await verify_database_identity(settings)
    db = Database.from_settings(settings)
    try:
        async with db.session_factory.begin() as session:
            await recover_owner(session, settings=settings, login=login, password=password)
    finally:
        await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize one local Novalton owner")
    parser.add_argument("login", help="Unique login (password is requested through the terminal)")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("Local terminal required", file=sys.stderr)
        return 1
    password = getpass.getpass("New Novalton password: ")
    confirmed = getpass.getpass("Confirm password: ")
    if password != confirmed:
        print("Passwords differ", file=sys.stderr)
        return 1
    try:
        asyncio.run(run_bootstrap(args.login, password))
    except (BootstrapDenied, ValueError) as exc:
        print(f"Bootstrap unavailable: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Bootstrap unavailable: database operation failed", file=sys.stderr)
        return 1
    print("Local owner initialized. Sign in through Novalton.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
