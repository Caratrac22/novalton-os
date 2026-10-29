"""Disabled-by-default paid generation boundary for trusted HTTP adapters.

The runtime does not register paid providers. This boundary deliberately accepts
only fixed destinations and never accepts a user supplied URL or raw API key.
Every attempt consumes a durable, unique reservation before any HTTP I/O. A
crash, timeout, cancellation or lost response burns that request ID permanently.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult
from novalton_api.infrastructure.providers.openai_compatible import OpenAICompatibleProvider
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.financial.service import denied, reserve, scoped_authorization
from novalton_api.modules.projects.models import Project

_DESTINATIONS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class PaidGenerationGateway:
    """One attempt, with a committed reservation and serialized revocation.

    This is a preparatory API, not a runtime feature toggle. The authorization
    row remains locked during the bounded I/O: a concurrent revocation cannot
    commit between the final check and the outbound attempt. Callers must not
    retry this method with the same or a new request ID after uncertain I/O.
    """

    def __init__(self, provider: OpenAICompatibleProvider) -> None:
        if (
            type(provider) is not OpenAICompatibleProvider
            or _DESTINATIONS.get(provider.provider_id) != provider._config.base_url
            or provider._config.api_key is None
        ):
            raise denied()
        self._provider = provider

    async def complete(
        self,
        session: AsyncSession,
        *,
        operator: OperatorAuthority,
        authorization_id: UUID,
        tenant_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        request_id: UUID,
        request: GenerationRequest,
        reserved_tokens: int,
        estimated_exposure: Decimal,
        timeout_seconds: float = 45,
    ) -> GenerationResult:
        if (
            request.max_output_tokens is None
            or reserved_tokens < request.max_output_tokens
            or not 0 < timeout_seconds <= 60
        ):
            raise denied()
        # reserve() locks the authorization and enforces scope, identity, model,
        # active grants, expiry and monotonic request/token/estimated quotas.
        await reserve(
            session,
            operator=operator,
            authorization_id=authorization_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            project_id=project_id,
            provider_id=self._provider.provider_id,
            model_id=request.model_id,
            currency="USD",
            request_id=request_id,
            tokens=reserved_tokens,
            estimated_exposure=estimated_exposure,
            reject_existing=True,
        )
        await session.commit()  # durable before any outbound I/O

        # Re-check after commit and serialize revocation through the actual call.
        # A DB failure or cancellation leaves the reservation consumed.
        try:
            await operator.require_human(
                session, "workspace.write", tenant_id=tenant_id, workspace_id=workspace_id
            )
            project = await session.scalar(
                select(Project)
                .where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                    Project.status == "ACTIVE",
                )
                .with_for_update(read=True)
            )
            if project is None:
                raise denied()
            row = await scoped_authorization(
                session,
                authorization_id=authorization_id,
                owner_id=operator.user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                project_id=project_id,
                lock=True,
            )
            if (
                row.revoked_at is not None
                or row.expires_at <= datetime.now(UTC)
                or row.provider_id != self._provider.provider_id
                or row.model_id != request.model_id
                or row.currency != "USD"
            ):
                raise denied()
            return await asyncio.wait_for(self._provider.complete(request), timeout=timeout_seconds)
        finally:
            await session.rollback()  # release the lock even on late/failed responses
