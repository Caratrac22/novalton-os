"""Health route."""

from fastapi import APIRouter

from novalton_api import __version__
from novalton_api.core.config import get_settings
from novalton_api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report API liveness without checking external dependencies."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="novalton-api",
        version=__version__,
        environment=settings.environment,
    )
