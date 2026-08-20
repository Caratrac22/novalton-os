import pytest

from novalton_api.core.config import Settings, SettingsError, get_settings

SETTING_VARIABLES = (
    "NOVALTON_ENV",
    "NOVALTON_LOG_LEVEL",
    "DATABASE_URL",
    "REDIS_URL",
    "QDRANT_URL",
    "NOVALTON_OPENAI_COMPATIBLE_BASE_URL",
    "NOVALTON_OPENAI_COMPATIBLE_API_KEY",
    "NOVALTON_OPENAI_COMPATIBLE_PROVIDER_ID",
    "NOVALTON_OPENROUTER_CATALOG_ENABLED",
    "NOVALTON_MODEL_CATALOG_FREE_ALLOWLIST",
    "NOVALTON_BOOTSTRAP_TENANT_ID",
    "NOVALTON_BOOTSTRAP_TENANT_NAME",
    "NOVALTON_BOOTSTRAP_TENANT_SLUG",
    "NOVALTON_BOOTSTRAP_WORKSPACE_ID",
    "NOVALTON_BOOTSTRAP_WORKSPACE_NAME",
    "NOVALTON_BOOTSTRAP_WORKSPACE_SLUG",
)


def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in SETTING_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    get_settings.cache_clear()


def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_environment(monkeypatch)

    settings = get_settings()

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url.startswith("postgresql://")
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.openrouter_catalog_enabled is False
    assert settings.model_catalog_free_allowlist_pairs == set()


def test_catalog_source_and_allowlist_require_explicit_valid_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_OPENROUTER_CATALOG_ENABLED", "true")
    with pytest.raises(SettingsError):
        Settings.from_environment()

    monkeypatch.setenv("NOVALTON_OPENAI_COMPATIBLE_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv(
        "NOVALTON_MODEL_CATALOG_FREE_ALLOWLIST",
        "openrouter::vendor/model-a,openrouter::vendor/model-b",
    )
    settings = Settings.from_environment()
    assert settings.openrouter_catalog_enabled is True
    assert settings.model_catalog_free_allowlist_pairs == {
        ("openrouter", "vendor/model-a"),
        ("openrouter", "vendor/model-b"),
    }


def test_settings_load_supported_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_ENV", "test")
    monkeypatch.setenv("NOVALTON_LOG_LEVEL", "warning")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/novalton")
    monkeypatch.setenv("REDIS_URL", "rediss://redis.example/1")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example")

    settings = Settings.from_environment()

    assert settings.environment == "test"
    assert settings.log_level == "WARNING"
    assert settings.database_url == "postgresql://db.example/novalton"
    assert settings.redis_url == "rediss://redis.example/1"
    assert settings.qdrant_url == "https://qdrant.example"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("NOVALTON_ENV", "staging"),
        ("NOVALTON_LOG_LEVEL", "verbose"),
        ("DATABASE_URL", "https://not-a-database.example"),
        ("REDIS_URL", "http://not-redis.example"),
        ("QDRANT_URL", "not-a-url"),
    ],
)
def test_invalid_configuration_is_rejected_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv(variable, value)

    with pytest.raises(SettingsError, match="Invalid application configuration") as exc_info:
        Settings.from_environment()

    assert value not in str(exc_info.value)
