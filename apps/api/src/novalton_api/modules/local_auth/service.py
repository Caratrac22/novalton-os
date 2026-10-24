"""Bounded local passwords and revocable bearer sessions for existing humans."""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    TenantOperatorMembership,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.local_auth.models import LocalCredential, LocalLoginThrottle, LocalSession

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16)
_LOGIN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,127}$")
_TOKEN = re.compile(r"^nvl_[A-Za-z0-9_-]{43}$")
_DUMMY_HASH = _HASHER.hash("unavailable-local-identity-dummy-password")


def normalize_login(login: str) -> str:
    value = login.strip().casefold()
    if _LOGIN.fullmatch(value) is None:
        raise ValueError("Invalid local account name")
    return value


def validate_password(password: str) -> None:
    if not 12 <= len(password) <= 128 or len(password.encode("utf-8")) > 512:
        raise ValueError("Password must contain between 12 and 128 characters")


def hash_password(password: str) -> str:
    validate_password(password)
    return _HASHER.hash(password)


def _verify(encoded: str, password: str) -> bool:
    try:
        return _HASHER.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


async def get_session(session: AsyncSession, token: str, *, lock: bool = False) -> LocalSession:
    if _TOKEN.fullmatch(token) is None:
        raise ApplicationError("local_session_invalid", "Session unavailable", status_code=401)
    statement = select(LocalSession).where(LocalSession.token_sha256 == token_digest(token))
    if lock:
        statement = statement.with_for_update(read=True)
    row = await session.scalar(statement.execution_options(populate_existing=True))
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        raise ApplicationError("local_session_invalid", "Session unavailable", status_code=401)
    return row


async def login(
    session: AsyncSession, *, login_name: str, password: str
) -> tuple[str, list[tuple[UUID, UUID]]]:
    # A single row per normalized login serializes retries even across API workers.
    normalized = login_name.strip().casefold()[:128]
    throttle_key = hashlib.sha256(normalized.encode()).hexdigest()
    now = datetime.now(UTC)
    await session.execute(
        insert(LocalLoginThrottle)
        .values(login_sha256=throttle_key, failures=0, window_start=now)
        .on_conflict_do_nothing()
    )
    throttle = await session.scalar(
        select(LocalLoginThrottle)
        .where(LocalLoginThrottle.login_sha256 == throttle_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert throttle is not None
    if throttle.window_start + timedelta(minutes=15) <= now:
        throttle.failures, throttle.window_start, throttle.locked_until = 0, now, None
    valid_name = _LOGIN.fullmatch(normalized) is not None
    credential = (
        await session.scalar(select(LocalCredential).where(LocalCredential.login == normalized))
        if valid_name
        else None
    )
    # Verify even unknown users to avoid a cheap username timing oracle.
    verified = _verify(credential.password_hash if credential else _DUMMY_HASH, password)
    user = await session.get(HumanOperator, credential.user_id) if credential and verified else None
    if (
        (throttle.locked_until is not None and throttle.locked_until > now)
        or not verified
        or user is None
        or not user.active
    ):
        throttle.failures += 1
        if throttle.failures >= 5:
            throttle.locked_until = now + timedelta(minutes=15)
        await session.commit()
        raise ApplicationError("local_login_invalid", "Identifiants indisponibles", status_code=401)
    scopes = list(
        (
            await session.execute(
                select(
                    WorkspaceOperatorPermission.tenant_id, WorkspaceOperatorPermission.workspace_id
                )
                .join(
                    TenantOperatorMembership,
                    (TenantOperatorMembership.user_id == WorkspaceOperatorPermission.user_id)
                    & (TenantOperatorMembership.tenant_id == WorkspaceOperatorPermission.tenant_id),
                )
                .where(
                    WorkspaceOperatorPermission.user_id == user.id,
                    WorkspaceOperatorPermission.permission == "workspace.read",
                    WorkspaceOperatorPermission.active.is_(True),
                    TenantOperatorMembership.active.is_(True),
                )
            )
        ).all()
    )
    if not scopes:
        await session.commit()
        raise ApplicationError("local_login_invalid", "Identifiants indisponibles", status_code=401)
    throttle.failures, throttle.locked_until = 0, None
    token = "nvl_" + secrets.token_urlsafe(32)
    session.add(
        LocalSession(
            user_id=user.id, token_sha256=token_digest(token), expires_at=now + timedelta(hours=1)
        )
    )
    await session.commit()
    return token, scopes


async def logout(session: AsyncSession, token: str) -> None:
    row = await get_session(session, token)
    await session.execute(
        update(LocalSession)
        .where(LocalSession.id == row.id, LocalSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()


async def verify_sensitive_password(
    session: AsyncSession, *, user_id: UUID, password: str
) -> LocalCredential:
    """Serialize and bound reauthentication attempts for sensitive account changes."""
    credential = await session.scalar(
        select(LocalCredential).where(LocalCredential.user_id == user_id).with_for_update()
    )
    if credential is None:
        raise ApplicationError(
            "local_reauth_invalid", "Identifiants indisponibles", status_code=401
        )
    key = hashlib.sha256(credential.login.encode()).hexdigest()
    now = datetime.now(UTC)
    await session.execute(
        insert(LocalLoginThrottle)
        .values(login_sha256=key, failures=0, window_start=now)
        .on_conflict_do_nothing()
    )
    throttle = await session.scalar(
        select(LocalLoginThrottle)
        .where(LocalLoginThrottle.login_sha256 == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert throttle is not None
    if throttle.window_start + timedelta(minutes=15) <= now:
        throttle.failures, throttle.window_start, throttle.locked_until = 0, now, None
    if (throttle.locked_until and throttle.locked_until > now) or not _verify(
        credential.password_hash, password
    ):
        throttle.failures += 1
        if throttle.failures >= 5:
            throttle.locked_until = now + timedelta(minutes=15)
        await session.commit()
        raise ApplicationError(
            "local_reauth_invalid", "Identifiants indisponibles", status_code=401
        )
    throttle.failures, throttle.locked_until = 0, None
    return credential


async def change_password(
    session: AsyncSession,
    *,
    token: str,
    current: str,
    replacement: str,
    tenant_id: UUID,
    workspace_id: UUID,
) -> None:
    row = await get_session(session, token, lock=True)
    credential = await verify_sensitive_password(session, user_id=row.user_id, password=current)
    encoded = hash_password(replacement)
    now = datetime.now(UTC)
    credential.password_hash, credential.changed_at = encoded, now
    await session.execute(
        update(LocalSession)
        .where(LocalSession.user_id == row.user_id, LocalSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            action="account.password.change",
            actor_type="local_user",
            actor_id=str(row.user_id),
            outcome="success",
        ),
        commit=False,
    )
    await session.commit()
