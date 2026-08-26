"""Catalog scoping, refresh lifecycle, validation, and transaction boundaries."""

import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import Settings
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.catalog import CatalogSourceRegistry
from novalton_api.infrastructure.providers.contracts import CatalogModel, ContractEnforcementGrade
from novalton_api.infrastructure.providers.errors import ProviderError
from novalton_api.modules.model_catalog import repository
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_catalog.schemas import (
    GovernedQualificationDiagnostic,
    ModelFilters,
    ModelStatus,
    RefreshResponse,
)
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


async def _require_workspace(session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID) -> None:
    if (
        await get_workspace_by_tenant_and_id(
            session, tenant_id=tenant_id, workspace_id=workspace_id
        )
        is None
    ):
        raise _not_found()


async def list_models(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int,
    offset: int,
    filters: ModelFilters,
) -> list[ModelDefinition]:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    return await repository.list_models(
        session,
        limit=limit,
        offset=offset,
        provider_id=filters.provider_id,
        status=filters.status.value if filters.status is not None else None,
    )


async def get_model(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    model_id: UUID,
) -> ModelDefinition:
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    model = await repository.get_model(session, model_id=model_id)
    if model is None:
        raise _not_found()
    return model


async def list_governed_qualification_diagnostics(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    settings: Settings,
) -> list[GovernedQualificationDiagnostic]:
    """Expose configured qualifications without source payloads, schemas, or credentials."""
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    catalog_by_identity = {
        (model.provider_id, model.provider_model_id): model
        for model in await repository.list_routing_candidates(session)
    }
    return [
        GovernedQualificationDiagnostic(
            provider_id=qualification.provider_id,
            provider_model_id=qualification.provider_model_id,
            qualification_present=True,
            enabled=qualification.enabled,
            qualification_source=qualification.qualification_source,
            contract_enforcement_grade=qualification.contract_enforcement_grade,
            upstream_provider_constraint=qualification.upstream_provider,
            provider_allow_fallbacks=False,
            provider_require_parameters=True,
            catalog_target_present=(
                model := catalog_by_identity.get(
                    (qualification.provider_id, qualification.provider_model_id)
                )
            )
            is not None,
            catalog_status=ModelStatus(model.status) if model is not None else None,
            structured_output_capability=model.structured_output if model is not None else None,
            context_window=model.context_window if model is not None else None,
            max_output_tokens=model.max_output_tokens if model is not None else None,
            free_allowlisted=model.free_allowlisted if model is not None else None,
        )
        for qualification in settings.governed_provider_qualifications
    ]


async def refresh_provider(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    provider_id: str,
    sources: CatalogSourceRegistry,
    free_allowlist: frozenset[tuple[str, str]],
) -> RefreshResponse:
    """Atomically replace one provider's authoritative freshness snapshot."""
    await _require_workspace(session, tenant_id=tenant_id, workspace_id=workspace_id)
    started_at = perf_counter()
    outcome = "success"
    model_count = 0
    try:
        source = sources.get(provider_id)
        received = await source.list_models()
        # Revalidate even custom/test sources before any write reaches the session.
        models = [CatalogModel.model_validate(model) for model in received]
        identifiers = [model.provider_model_id for model in models]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate model identifiers")
        model_count = len(models)

        verified_at = datetime.now(UTC)
        for model in models:
            grade = model.contract_enforcement_grade
            if grade is None:
                grade = (
                    ContractEnforcementGrade.BEST_EFFORT
                    if model.structured_output is True
                    else ContractEnforcementGrade.UNSUPPORTED
                )
            enforcement_source = model.enforcement_metadata_source or (
                "catalog_structured_output_capability"
                if model.structured_output is True
                else "catalog_unknown"
            )
            await repository.upsert_model(
                session,
                provider_id=provider_id,
                provider_model_id=model.provider_model_id,
                values={
                    "display_name": model.display_name,
                    "status": "AVAILABLE",
                    "context_window": model.context_window,
                    "max_output_tokens": model.max_output_tokens,
                    "reasoning": model.reasoning,
                    "coding": model.coding,
                    "tool_calling": model.tool_calling,
                    "structured_output": model.structured_output,
                    "contract_enforcement_grade": grade.value,
                    "enforcement_metadata_source": enforcement_source,
                    "vision": model.vision,
                    "input_price_per_million": model.input_price_per_million,
                    "output_price_per_million": model.output_price_per_million,
                    "currency": model.currency,
                    "free_allowlisted": (provider_id, model.provider_model_id) in free_allowlist,
                    "family": model.family,
                    "revision": model.revision,
                    "last_verified_at": verified_at,
                },
            )
        stale_count = await repository.mark_missing_stale(
            session,
            provider_id=provider_id,
            returned_model_ids=set(identifiers),
        )
        await session.commit()
        return RefreshResponse(
            provider_id=provider_id,
            verified_count=len(models),
            stale_count=stale_count,
            verified_at=verified_at,
        )
    except ProviderError as exc:
        outcome = exc.failure.value
        await session.rollback()
        raise ApplicationError(
            "model_catalog_refresh_failed",
            "Model catalog refresh failed",
            status_code=502,
        ) from None
    except (ValidationError, ValueError, TypeError):
        outcome = "malformed_response"
        await session.rollback()
        raise ApplicationError(
            "model_catalog_refresh_failed",
            "Model catalog refresh failed",
            status_code=502,
        ) from None
    except SQLAlchemyError:
        outcome = "persistence_failed"
        await session.rollback()
        raise ApplicationError(
            "model_catalog_persistence_failed",
            "Model catalog could not be persisted",
            status_code=500,
        ) from None
    finally:
        logger.info(
            "Model catalog refresh completed",
            extra={
                "event": "model_catalog.refresh.completed",
                "provider_id": provider_id,
                "outcome_class": outcome,
                "model_count": model_count,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
