"""Validated, environment-backed application configuration."""

import logging
from functools import lru_cache
from os import environ
from typing import ClassVar, Literal, Self
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from novalton_api.infrastructure.providers.urls import validate_provider_base_url


class SettingsError(RuntimeError):
    """Raised when application configuration is invalid."""


class Settings(BaseModel):
    """Central application settings with local-development defaults."""

    model_config = ConfigDict(frozen=True)

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql://novalton:novalton_dev_only@localhost:5432/novalton"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: SecretStr | None = None
    provider_connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    provider_read_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    provider_write_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    provider_pool_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    provider_max_response_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    bootstrap_tenant_id: UUID = UUID("89cfc055-366e-5bcb-b65f-4f367185bf6d")
    bootstrap_tenant_name: str = "Local Tenant"
    bootstrap_tenant_slug: str = "tenant_local"
    bootstrap_workspace_id: UUID = UUID("b640b64f-8e55-53e8-a5b2-3beff9d5af82")
    bootstrap_workspace_name: str = "Default Workspace"
    bootstrap_workspace_slug: str = "workspace_default"

    _environment_names: ClassVar[dict[str, str]] = {
        "environment": "NOVALTON_ENV",
        "log_level": "NOVALTON_LOG_LEVEL",
        "database_url": "DATABASE_URL",
        "redis_url": "REDIS_URL",
        "qdrant_url": "QDRANT_URL",
        "openai_compatible_base_url": "NOVALTON_OPENAI_COMPATIBLE_BASE_URL",
        "openai_compatible_api_key": "NOVALTON_OPENAI_COMPATIBLE_API_KEY",
        "provider_connect_timeout_seconds": "NOVALTON_PROVIDER_CONNECT_TIMEOUT_SECONDS",
        "provider_read_timeout_seconds": "NOVALTON_PROVIDER_READ_TIMEOUT_SECONDS",
        "provider_write_timeout_seconds": "NOVALTON_PROVIDER_WRITE_TIMEOUT_SECONDS",
        "provider_pool_timeout_seconds": "NOVALTON_PROVIDER_POOL_TIMEOUT_SECONDS",
        "provider_max_response_bytes": "NOVALTON_PROVIDER_MAX_RESPONSE_BYTES",
        "bootstrap_tenant_id": "NOVALTON_BOOTSTRAP_TENANT_ID",
        "bootstrap_tenant_name": "NOVALTON_BOOTSTRAP_TENANT_NAME",
        "bootstrap_tenant_slug": "NOVALTON_BOOTSTRAP_TENANT_SLUG",
        "bootstrap_workspace_id": "NOVALTON_BOOTSTRAP_WORKSPACE_ID",
        "bootstrap_workspace_name": "NOVALTON_BOOTSTRAP_WORKSPACE_NAME",
        "bootstrap_workspace_slug": "NOVALTON_BOOTSTRAP_WORKSPACE_SLUG",
    }

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in logging.getLevelNamesMapping():
            raise ValueError("unsupported log level")
        return normalized

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        return cls._validate_url(value, {"postgresql", "postgresql+asyncpg"}, "database")

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        return cls._validate_url(value, {"redis", "rediss"}, "Redis")

    @field_validator("qdrant_url")
    @classmethod
    def validate_qdrant_url(cls, value: str) -> str:
        return cls._validate_url(value, {"http", "https"}, "Qdrant")

    @field_validator("openai_compatible_base_url")
    @classmethod
    def validate_openai_compatible_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_provider_base_url(value)

    @staticmethod
    def _validate_url(value: str, schemes: set[str], label: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in schemes or not parsed.hostname:
            raise ValueError(f"invalid {label} URL")
        return value

    @classmethod
    def from_environment(cls) -> Self:
        """Load known settings without reading unrelated environment values."""
        values = {
            field: environ[variable]
            for field, variable in cls._environment_names.items()
            if variable in environ
        }
        try:
            return cls.model_validate(values)
        except ValidationError:
            # Pydantic errors may contain rejected values, including URL credentials.
            raise SettingsError("Invalid application configuration") from None


@lru_cache
def get_settings() -> Settings:
    """Return the process configuration loaded once from the environment."""
    return Settings.from_environment()
