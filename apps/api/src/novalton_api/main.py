"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from novalton_api import __version__
from novalton_api.api.v1.health import router as health_router
from novalton_api.core.config import get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import register_exception_handlers
from novalton_api.core.logging import configure_logging
from novalton_api.core.middleware import CorrelationIdMiddleware
from novalton_api.infrastructure.providers.catalog import CatalogSourceRegistry
from novalton_api.infrastructure.providers.openai_compatible import OpenAICompatibleConfig
from novalton_api.infrastructure.providers.openrouter_catalog import OpenRouterCatalogSource
from novalton_api.modules.approvals.routes import router as approvals_router
from novalton_api.modules.model_catalog.routes import router as model_catalog_router
from novalton_api.modules.policy.routes import router as policy_router
from novalton_api.modules.projects.routes import router as projects_router
from novalton_api.modules.runtime_events.routes import router as runtime_events_router
from novalton_api.modules.tasks.routes import router as tasks_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Configure process-level concerns at application startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database.from_settings(settings)
    application.state.database = database
    owns_catalog_sources = not hasattr(application.state, "catalog_sources")
    if owns_catalog_sources:
        sources = ()
        if settings.openrouter_catalog_enabled and settings.openai_compatible_base_url is not None:
            sources = (
                OpenRouterCatalogSource(
                    OpenAICompatibleConfig(
                        provider_id=settings.openai_compatible_provider_id,
                        base_url=settings.openai_compatible_base_url,
                        api_key=settings.openai_compatible_api_key,
                        connect_timeout_seconds=settings.provider_connect_timeout_seconds,
                        read_timeout_seconds=settings.provider_read_timeout_seconds,
                        write_timeout_seconds=settings.provider_write_timeout_seconds,
                        pool_timeout_seconds=settings.provider_pool_timeout_seconds,
                        max_response_bytes=settings.provider_max_response_bytes,
                    )
                ),
            )
        application.state.catalog_sources = CatalogSourceRegistry(sources)
    logging.getLogger(__name__).info("API started", extra={"event": "api.started"})
    try:
        yield
    finally:
        if owns_catalog_sources:
            await application.state.catalog_sources.aclose()
        await database.dispose()


def create_app(*, catalog_sources: CatalogSourceRegistry | None = None) -> FastAPI:
    """Create and wire the FastAPI application."""
    application = FastAPI(title="Novalton OS API", version=__version__, lifespan=lifespan)
    if catalog_sources is not None:
        application.state.catalog_sources = catalog_sources
    register_exception_handlers(application)
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(projects_router, prefix="/api/v1")
    application.include_router(tasks_router, prefix="/api/v1")
    application.include_router(runtime_events_router, prefix="/api/v1")
    application.include_router(approvals_router, prefix="/api/v1")
    application.include_router(policy_router, prefix="/api/v1")
    application.include_router(model_catalog_router, prefix="/api/v1")
    return application


app = create_app()
