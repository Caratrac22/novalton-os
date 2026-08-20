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
from novalton_api.modules.projects.routes import router as projects_router
from novalton_api.modules.tasks.routes import router as tasks_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Configure process-level concerns at application startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database.from_settings(settings)
    application.state.database = database
    logging.getLogger(__name__).info("API started", extra={"event": "api.started"})
    try:
        yield
    finally:
        await database.dispose()


def create_app() -> FastAPI:
    """Create and wire the FastAPI application."""
    application = FastAPI(title="Novalton OS API", version=__version__, lifespan=lifespan)
    register_exception_handlers(application)
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(projects_router, prefix="/api/v1")
    application.include_router(tasks_router, prefix="/api/v1")
    return application


app = create_app()
