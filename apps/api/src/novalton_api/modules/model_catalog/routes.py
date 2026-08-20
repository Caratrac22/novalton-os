"""Thin scoped HTTP routes over the global model catalog."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.database import get_async_session
from novalton_api.infrastructure.providers.catalog import CatalogSourceRegistry
from novalton_api.modules.model_catalog import service
from novalton_api.modules.model_catalog.schemas import (
    ModelDefinitionListResponse,
    ModelDefinitionResponse,
    ModelFilters,
    ModelStatus,
    ProviderIdentifier,
    RefreshRequest,
    RefreshResponse,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/models",
    tags=["models"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]


def get_catalog_sources(request: Request) -> CatalogSourceRegistry:
    return request.app.state.catalog_sources


@router.get("", response_model=ModelDefinitionListResponse)
async def list_models(
    tenant_id: UUID,
    workspace_id: UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    provider_id: Annotated[ProviderIdentifier | None, Query()] = None,
    status: Annotated[ModelStatus | None, Query()] = None,
) -> ModelDefinitionListResponse:
    models = await service.list_models(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        filters=ModelFilters(provider_id=provider_id, status=status),
    )
    return ModelDefinitionListResponse(items=models, limit=limit, offset=offset)


@router.get("/{model_id}", response_model=ModelDefinitionResponse)
async def get_model(
    tenant_id: UUID, workspace_id: UUID, model_id: UUID, session: Session
) -> ModelDefinitionResponse:
    model = await service.get_model(
        session, tenant_id=tenant_id, workspace_id=workspace_id, model_id=model_id
    )
    return ModelDefinitionResponse.model_validate(model)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_models(
    tenant_id: UUID,
    workspace_id: UUID,
    data: RefreshRequest,
    session: Session,
    sources: Annotated[CatalogSourceRegistry, Depends(get_catalog_sources)],
) -> RefreshResponse:
    return await service.refresh_provider(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        provider_id=data.provider_id,
        sources=sources,
        free_allowlist=get_settings().model_catalog_free_allowlist_pairs,
    )
