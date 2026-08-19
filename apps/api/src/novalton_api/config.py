"""Environment-backed application configuration."""

from dataclasses import dataclass
from functools import lru_cache
from os import getenv


@dataclass(frozen=True, slots=True)
class Settings:
    """Minimal settings needed by the repository scaffold."""

    environment: str = "development"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Load and cache application settings from the environment."""
    return Settings(
        environment=getenv("NOVALTON_ENV", "development"),
        log_level=getenv("NOVALTON_LOG_LEVEL", "INFO").upper(),
    )
