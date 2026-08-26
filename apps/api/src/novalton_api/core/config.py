"""Validated, environment-backed application configuration."""

import logging
import re
from functools import lru_cache
from os import environ
from typing import ClassVar, Literal, Self
from urllib.parse import urlparse
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

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
    openai_compatible_provider_id: str = Field(
        default="openrouter", min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$"
    )
    openai_compatible_require_parameters: bool = False
    openai_compatible_response_healing: bool = False
    openrouter_catalog_enabled: bool = False
    model_catalog_free_allowlist: tuple[str, ...] = ()
    model_router_force_model: str | None = None
    provider_connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    provider_read_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    provider_write_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    provider_pool_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    provider_max_response_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    model_output_token_safety_ceiling: int = Field(default=65_536, ge=1, le=65_536)
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
        "openai_compatible_provider_id": "NOVALTON_OPENAI_COMPATIBLE_PROVIDER_ID",
        "openai_compatible_require_parameters": "NOVALTON_OPENAI_COMPATIBLE_REQUIRE_PARAMETERS",
        "openai_compatible_response_healing": "NOVALTON_OPENAI_COMPATIBLE_RESPONSE_HEALING",
        "openrouter_catalog_enabled": "NOVALTON_OPENROUTER_CATALOG_ENABLED",
        "model_catalog_free_allowlist": "NOVALTON_MODEL_CATALOG_FREE_ALLOWLIST",
        "model_router_force_model": "NOVALTON_MODEL_ROUTER_FORCE_MODEL",
        "provider_connect_timeout_seconds": "NOVALTON_PROVIDER_CONNECT_TIMEOUT_SECONDS",
        "provider_read_timeout_seconds": "NOVALTON_PROVIDER_READ_TIMEOUT_SECONDS",
        "provider_write_timeout_seconds": "NOVALTON_PROVIDER_WRITE_TIMEOUT_SECONDS",
        "provider_pool_timeout_seconds": "NOVALTON_PROVIDER_POOL_TIMEOUT_SECONDS",
        "provider_max_response_bytes": "NOVALTON_PROVIDER_MAX_RESPONSE_BYTES",
        "model_output_token_safety_ceiling": "NOVALTON_MODEL_OUTPUT_TOKEN_SAFETY_CEILING",
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

    @field_validator("model_catalog_free_allowlist", mode="before")
    @classmethod
    def validate_model_catalog_free_allowlist(cls, value: object) -> object:
        entries = (
            (
                tuple(item.strip() for item in value.split(","))
                if isinstance(value, str) and value
                else ()
            )
            if isinstance(value, str)
            else value
        )
        if not isinstance(entries, tuple) or len(entries) > 32:
            raise ValueError("model catalog free allowlist must contain at most 32 entries")
        pattern = re.compile(r"^[a-z][a-z0-9_-]{0,63}::[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
        if any(not isinstance(item, str) or pattern.fullmatch(item) is None for item in entries):
            raise ValueError("invalid model catalog free allowlist entry")
        if len(entries) != len(set(entries)):
            raise ValueError("duplicate model catalog free allowlist entry")
        return entries

    @field_validator("model_router_force_model")
    @classmethod
    def validate_model_router_force_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        pattern = re.compile(r"^[a-z][a-z0-9_-]{0,63}::[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
        if pattern.fullmatch(value) is None:
            raise ValueError("invalid forced model router entry")
        return value

    @property
    def model_catalog_free_allowlist_pairs(self) -> frozenset[tuple[str, str]]:
        """Return explicit exact provider/model pairs; price never affects membership."""
        return frozenset(tuple(entry.split("::", 1)) for entry in self.model_catalog_free_allowlist)

    @property
    def model_router_force_model_pair(self) -> tuple[str, str] | None:
        """Return the optional exact provider/model routing override."""
        if self.model_router_force_model is None:
            return None
        provider_id, provider_model_id = self.model_router_force_model.split("::", 1)
        return provider_id, provider_model_id

    @model_validator(mode="after")
    def validate_catalog_source_configuration(self) -> Self:
        if self.openrouter_catalog_enabled and self.openai_compatible_base_url is None:
            raise ValueError("OpenRouter catalog requires a configured provider base URL")
        return self

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
