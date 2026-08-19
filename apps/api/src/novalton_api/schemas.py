"""API response schemas."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Public liveness response."""

    status: Literal["ok"]
    service: Literal["novalton-api"]
    version: str
    environment: str
