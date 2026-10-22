"""Pinned-key OIDC access-token adapter. Deployment owns login and secure cookie issuance."""

from datetime import UTC, datetime
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.durable_dispatch.identity import (
    FederatedOperatorIdentity,
    HumanOperator,
)
from novalton_api.modules.durable_dispatch.oidc_keys import signing_key
from novalton_api.modules.durable_dispatch.operator import (
    OperatorAuthority,
    federated_operator_authority,
    local_operator_authority,
)


def _unauthorized() -> ApplicationError:
    return ApplicationError(
        "operator_session_invalid", "Operator session unavailable", status_code=401
    )


async def authenticate_session(
    session: AsyncSession,
    *,
    token: str,
    tenant_id: UUID,
    workspace_id: UUID,
) -> OperatorAuthority:
    """Use only configured RS256 verification; a browser assertion is never an identity."""
    if token.startswith("nvl_"):
        from novalton_api.modules.local_auth.service import get_session

        local = await get_session(session, token, lock=True)
        human = await session.get(HumanOperator, local.user_id)
        if human is None or not human.active:
            raise _unauthorized()
        return local_operator_authority(
            user=human,
            local_session_id=local.id,
            expires_at=local.expires_at,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
    settings = get_settings()
    issuer, audience, public_key, jwks_uri = (
        settings.operator_oidc_issuer,
        settings.operator_oidc_audience,
        settings.operator_oidc_public_key_pem,
        settings.operator_oidc_jwks_uri,
    )
    if (
        not issuer
        or not audience
        or (bool(public_key) == bool(jwks_uri))
        or not issuer.startswith("https://")
        or not token
        or len(token) > 8192
    ):
        raise _unauthorized()
    try:
        key = (
            await signing_key(issuer=issuer, jwks_uri=jwks_uri, token=token)
            if jwks_uri
            else public_key
        )
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["iss", "sub", "aud", "iat", "exp", "auth_time"]},
        )
        subject = claims["sub"]
        issued, expires, authenticated = claims["iat"], claims["exp"], claims["auth_time"]
        if (
            not isinstance(subject, str)
            or not 1 <= len(subject) <= 256
            or not isinstance(issued, int)
            or not isinstance(expires, int)
            or not isinstance(authenticated, int)
            or authenticated > issued
            or issued - authenticated > 3600
            or expires <= issued
            or expires - issued > 3600
        ):
            raise _unauthorized()
        expires_at = datetime.fromtimestamp(expires, UTC)
    except (jwt.PyJWTError, ValueError, OverflowError, TypeError, KeyError) as exc:
        raise _unauthorized() from exc
    binding = await session.scalar(
        select(FederatedOperatorIdentity)
        .where(
            FederatedOperatorIdentity.issuer == issuer,
            FederatedOperatorIdentity.subject == subject,
        )
        .execution_options(populate_existing=True)
    )
    if binding is None or not binding.active:
        raise _unauthorized()
    user = await session.scalar(
        select(HumanOperator)
        .where(HumanOperator.id == binding.user_id)
        .execution_options(populate_existing=True)
    )
    if user is None or not user.active:
        raise _unauthorized()
    return federated_operator_authority(
        user=user,
        issuer=issuer,
        subject=subject,
        expires_at=expires_at,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
