import pytest

from novalton_api.core.config import Settings, SettingsError, get_settings

SETTING_VARIABLES = (
    "NOVALTON_ENV",
    "NOVALTON_LOG_LEVEL",
    "DATABASE_URL",
    "REDIS_URL",
    "QDRANT_URL",
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
