"""Health route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from novalton_api import __version__
from novalton_api.core.config import get_settings
from novalton_api.core.database import Database, get_database
from novalton_api.schemas import DependenciesHealthResponse, DependencyHealth, HealthResponse

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


@router.get("/health/dependencies", response_model=DependenciesHealthResponse)
async def dependency_health(
    response: Response,
    database: Annotated[Database, Depends(get_database)],
) -> DependenciesHealthResponse:
    """Report sanitized PostgreSQL dependency health."""
    postgres_is_healthy = await database.check_connection()
    overall_status = "healthy" if postgres_is_healthy else "unhealthy"
    if not postgres_is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return DependenciesHealthResponse(
        status=overall_status,
        dependencies={
            "postgres": DependencyHealth(status=overall_status),
        },
    )
