"""Human-only HTTP boundary for workspace APIs; internal Python services remain separate."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.identity import TenantOperatorMembership
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.durable_dispatch.sessions import authenticate_session


async def require_saas_access(
    request: Request,
    tenant_id: UUID,
    workspace_id: UUID,
    session: Annotated[AsyncSession, Depends(get_async_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> OperatorAuthority | None:
    settings = get_settings()
    if settings.test_legacy_api_auth_bypass:
        if settings.environment != "test":
            raise ApplicationError(
                "invalid_test_authority", "Test authority unavailable", status_code=503
            )
        return
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApplicationError("saas_auth_required", "Session required", status_code=401)
    token = authorization.removeprefix("Bearer ")
    if token != token.strip() or (token.count(".") != 2 and not token.startswith("nvl_")):
        raise ApplicationError("saas_auth_required", "Session required", status_code=401)
    launch_mutation = request.method == "POST" and "/launch-authorizations" in request.url.path
    operator = await authenticate_session(
        session,
        token=token,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        lock_local_session=not launch_mutation,
    )
    if launch_mutation:
        # The launch route locks and rechecks the complete identity, grants,
        # membership role and recent local session before any mutation. Holding
        # shared locks here first would deadlock a concurrent exclusive recheck.
        return operator
    permission = "workspace.read" if request.method in {"GET", "HEAD"} else "workspace.write"
    await operator.require_human(
        session, permission, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if request.url.path.endswith("/events/stream"):
        # The FastAPI dependency may live as long as the response stream.
        # Release its shared grant lock now; each polling session reauthorizes.
        await session.rollback()
    if permission == "workspace.write":
        role = await session.scalar(
            select(TenantOperatorMembership.role).where(
                TenantOperatorMembership.user_id == operator.user_id,
                TenantOperatorMembership.tenant_id == tenant_id,
            )
        )
        if role == "VIEWER":
            raise ApplicationError("saas_forbidden", "Workspace access denied", status_code=403)
    return operator
