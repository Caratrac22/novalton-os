"""API response schemas."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Public liveness response."""

    status: Literal["ok"]
    service: Literal["novalton-api"]
    version: str
    environment: str


class DependencyHealth(BaseModel):
    """Health state for one external dependency."""

    status: Literal["healthy", "unhealthy"]


class DependenciesHealthResponse(BaseModel):
    """Extensible dependency health response."""

    status: Literal["healthy", "unhealthy"]
    dependencies: dict[str, DependencyHealth]
