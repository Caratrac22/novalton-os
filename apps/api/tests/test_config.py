import pytest

from novalton_api.core.config import Settings, SettingsError, get_settings

SETTING_VARIABLES = (
    "NOVALTON_ENV",
    "NOVALTON_LOG_LEVEL",
    "DATABASE_URL",
    "NOVALTON_TEST_DATABASE_URL",
    "REDIS_URL",
    "QDRANT_URL",
    "NOVALTON_OPENAI_COMPATIBLE_BASE_URL",
    "NOVALTON_OPENAI_COMPATIBLE_API_KEY",
    "NOVALTON_OPENAI_COMPATIBLE_PROVIDER_ID",
    "NOVALTON_OPENAI_COMPATIBLE_REQUIRE_PARAMETERS",
    "NOVALTON_OPENAI_COMPATIBLE_RESPONSE_HEALING",
    "NOVALTON_OPENROUTER_CATALOG_ENABLED",
    "NOVALTON_GOVERNED_PROVIDER_QUALIFICATIONS",
    "NOVALTON_MODEL_CATALOG_FREE_ALLOWLIST",
    "NOVALTON_MODEL_ROUTER_FORCE_MODEL",
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
    # The session fixture redirects direct Settings() use to novalton_test. These unit tests
    # intentionally exercise the independent development profile instead.
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/novalton")
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
    assert settings.model_router_force_model_pair is None


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


def test_model_router_force_model_parses_exact_provider_model_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_MODEL_ROUTER_FORCE_MODEL", "openrouter::vendor/model-a")

    settings = Settings.from_environment()

    assert settings.model_router_force_model == "openrouter::vendor/model-a"
    assert settings.model_router_force_model_pair == ("openrouter", "vendor/model-a")


def test_governed_provider_qualifications_parse_bounded_json_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv(
        "NOVALTON_GOVERNED_PROVIDER_QUALIFICATIONS",
        '[{"provider_id":"openrouter","provider_model_id":"vendor/model-a",'
        '"upstream_provider":"openai","contract_enforcement_grade":"PROVIDER_ENFORCED",'
        '"qualification_source":"PROVIDER_DOCUMENTATION","enabled":true}]',
    )

    settings = Settings.from_environment()

    qualification = settings.governed_provider_qualifications[0]
    assert qualification.provider_model_id == "vendor/model-a"
    assert qualification.upstream_provider == "openai"
    assert qualification.contract_enforcement_grade == "PROVIDER_ENFORCED"


@pytest.mark.parametrize(
    "value",
    [
        "not-json",
        '[{"provider_id":"OpenRouter","provider_model_id":"vendor/model",'
        '"contract_enforcement_grade":"PROVIDER_ENFORCED",'
        '"qualification_source":"OPERATOR_CONFIGURATION"}]',
        '[{"provider_id":"openrouter","provider_model_id":"vendor/model",'
        '"contract_enforcement_grade":"BEST_EFFORT",'
        '"qualification_source":"OPERATOR_CONFIGURATION"}]',
    ],
)
def test_invalid_governed_provider_qualification_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_GOVERNED_PROVIDER_QUALIFICATIONS", value)

    with pytest.raises(SettingsError, match="Invalid application configuration"):
        Settings.from_environment()


def test_settings_load_supported_development_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_ENV", "development")
    monkeypatch.setenv("NOVALTON_LOG_LEVEL", "warning")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/novalton")
    monkeypatch.setenv("REDIS_URL", "rediss://redis.example/1")
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example")

    settings = Settings.from_environment()

    assert settings.environment == "development"
    assert settings.log_level == "WARNING"
    assert settings.database_url == "postgresql://db.example/novalton"
    assert settings.redis_url == "rediss://redis.example/1"
    assert settings.qdrant_url == "https://qdrant.example"


@pytest.mark.parametrize(
    ("database_url", "test_database_url", "message"),
    [
        ("postgresql://db.example/novalton_test", None, "test database"),
        ("postgresql://db.example/anything_test", None, "test database"),
        (
            "postgresql://db.example/novalton",
            "postgresql://db.example/novalton",
            "matches test database",
        ),
    ],
)
def test_development_profile_rejects_test_database_combinations(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    test_database_url: str | None,
    message: str,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", database_url)
    if test_database_url is not None:
        monkeypatch.setenv("NOVALTON_TEST_DATABASE_URL", test_database_url)

    with pytest.raises(SettingsError, match=message) as error:
        Settings.from_environment()

    assert "db.example" not in str(error.value)


@pytest.mark.parametrize(
    ("database_url", "test_database_url"),
    [
        ("postgresql://db.example/novalton_test", None),
        ("postgresql://db.example/novalton_test", "postgresql://db.example/other_test"),
        ("postgresql://db.example/other_test", "postgresql://db.example/other_test"),
    ],
)
def test_test_profile_requires_the_exact_configured_novalton_test_database(
    monkeypatch: pytest.MonkeyPatch, database_url: str, test_database_url: str | None
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("NOVALTON_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    if test_database_url is not None:
        monkeypatch.setenv("NOVALTON_TEST_DATABASE_URL", test_database_url)

    with pytest.raises(SettingsError) as error:
        Settings.from_environment()

    assert "db.example" not in str(error.value)


def test_test_profile_accepts_exact_isolated_database(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_environment(monkeypatch)
    url = "postgresql://db.example/novalton_test"
    monkeypatch.setenv("NOVALTON_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("NOVALTON_TEST_DATABASE_URL", url)

    assert Settings.from_environment().test_database_url == url


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("NOVALTON_ENV", "staging"),
        ("NOVALTON_LOG_LEVEL", "verbose"),
        ("DATABASE_URL", "https://not-a-database.example"),
        ("REDIS_URL", "http://not-redis.example"),
        ("QDRANT_URL", "not-a-url"),
        ("NOVALTON_MODEL_ROUTER_FORCE_MODEL", "openrouter/vendor/model"),
        ("NOVALTON_MODEL_ROUTER_FORCE_MODEL", "OpenRouter::vendor/model"),
        ("NOVALTON_MODEL_ROUTER_FORCE_MODEL", "openrouter::"),
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
