"""Local login issues opaque sessions; scoped account actions reuse SaaS grants."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.sessions import authenticate_session
from novalton_api.modules.local_auth import service

router = APIRouter(prefix="/local-auth", tags=["local-auth"])
scoped_router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/account", tags=["account"]
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    login: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    current: str = Field(min_length=1, max_length=128)
    replacement: str = Field(min_length=12, max_length=128)


def bearer(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise ApplicationError("local_session_invalid", "Session unavailable", status_code=401)
    return authorization.removeprefix("Bearer ")


@router.post("/login")
async def login(data: LoginInput, session: Session) -> dict[str, object]:
    token, scopes = await service.login(session, login_name=data.login, password=data.password)
    return {
        "token": token,
        "expires_in": 3600,
        "scopes": [
            {"tenant_id": str(tenant), "workspace_id": str(workspace)}
            for tenant, workspace in scopes
        ],
    }


@router.post("/logout", status_code=204)
async def logout(session: Session, authorization: Annotated[str | None, Header()] = None) -> None:
    await service.logout(session, bearer(authorization))


@scoped_router.get("/me")
async def me(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    operator = await authenticate_session(
        session, token=bearer(authorization), tenant_id=tenant_id, workspace_id=workspace_id
    )
    await operator.require_human(
        session, "workspace.read", tenant_id=tenant_id, workspace_id=workspace_id
    )
    return {"id": str(operator.user_id), "label": operator._label}


@scoped_router.post("/password", status_code=204)
async def password_change(
    tenant_id: UUID,
    workspace_id: UUID,
    data: PasswordInput,
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    token = bearer(authorization)
    if not token.startswith("nvl_"):
        raise ApplicationError("local_account_required", "Compte Novalton requis", status_code=403)
    operator = await authenticate_session(
        session, token=token, tenant_id=tenant_id, workspace_id=workspace_id
    )
    await operator.require_human(
        session, "workspace.read", tenant_id=tenant_id, workspace_id=workspace_id
    )
    await service.change_password(
        session,
        token=token,
        current=data.current,
        replacement=data.replacement,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
