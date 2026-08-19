"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from novalton_api import __version__
from novalton_api.api.v1.health import router as health_router
from novalton_api.config import get_settings
from novalton_api.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Configure process-level concerns at application startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("API started", extra={"event": "api.started"})
    yield


app = FastAPI(title="Novalton OS API", version=__version__, lifespan=lifespan)
app.include_router(health_router, prefix="/api/v1")
