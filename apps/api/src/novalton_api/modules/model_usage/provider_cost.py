"""Explicit, internal OpenRouter usage reconciliation with no invoice claim."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.model_usage.models import ModelRun, ProviderCostObservation


@dataclass(frozen=True)
class ReportedCost:
    generation_id: str
    amount: Decimal
    response_sha256: str


def _unavailable() -> ApplicationError:
    return ApplicationError(
        "provider_cost_unavailable", "Provider cost unavailable", status_code=409
    )


async def fetch_openrouter_cost(
    generation_id: str, *, api_key: str, transport: httpx.AsyncBaseTransport | None = None
) -> ReportedCost:
    """Fetch a single ID from the authenticated, fixed-origin generation API."""
    if (
        not generation_id.startswith("gen-")
        or len(generation_id) > 128
        or not generation_id.replace("-", "").replace("_", "").isalnum()
        or not api_key
    ):
        raise _unavailable()
    try:
        async with (
            httpx.AsyncClient(timeout=5, follow_redirects=False, transport=transport) as client,
            client.stream(
                "GET",
                "https://openrouter.ai/api/v1/generation",
                params={"id": generation_id},
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            ) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError("Oversized generation metadata")
        data = json.loads(body, parse_float=Decimal)["data"]
        if not isinstance(data, dict) or data.get("id") != generation_id:
            raise ValueError("Generation identity mismatch")
        raw = data["total_cost"]
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
            raise ValueError("Cost unavailable")
        amount = Decimal(str(raw))
        if not amount.is_finite() or not 0 <= amount < 1_000_000_000:
            raise ValueError("Cost outside supported range")
        return ReportedCost(
            generation_id,
            amount.quantize(Decimal("0.0000000001")),
            hashlib.sha256(body).hexdigest(),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise _unavailable() from exc


async def reconcile_openrouter_cost(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    model_run_id: UUID,
    api_key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ProviderCostObservation:
    """No public route. The caller must supply a trusted provider credential.

    The network lookup occurs before the row lock. A concurrent result is
    serialized on the exact ModelRun; a divergent observation is never silently
    substituted for earlier evidence. Unknown/timeouts leave no zero-cost row.
    """
    run = await session.scalar(
        select(ModelRun).where(
            ModelRun.id == model_run_id,
            ModelRun.tenant_id == tenant_id,
            ModelRun.workspace_id == workspace_id,
        )
    )
    if (
        run is None
        or run.provider_id != "openrouter"
        or run.status != "SUCCEEDED"
        or run.provider_generation_id is None
    ):
        raise _unavailable()
    generation_id = run.provider_generation_id
    reported = await fetch_openrouter_cost(generation_id, api_key=api_key, transport=transport)
    locked = await session.scalar(
        select(ModelRun)
        .where(
            ModelRun.id == model_run_id,
            ModelRun.tenant_id == tenant_id,
            ModelRun.workspace_id == workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        locked is None
        or locked.provider_generation_id != generation_id
        or locked.status != "SUCCEEDED"
    ):
        raise _unavailable()
    existing = await session.get(ProviderCostObservation, model_run_id)
    if existing is not None:
        if (existing.provider_id, existing.generation_id, existing.reported_cost) != (
            "openrouter",
            generation_id,
            reported.amount,
        ):
            raise ApplicationError(
                "provider_cost_divergence", "Provider cost changed", status_code=409
            )
        return existing
    evidence = ProviderCostObservation(
        model_run_id=model_run_id,
        provider_id="openrouter",
        generation_id=generation_id,
        reported_cost=reported.amount,
        response_sha256=reported.response_sha256,
        observed_at=datetime.now(UTC),
    )
    session.add(evidence)
    await session.flush()
    return evidence
