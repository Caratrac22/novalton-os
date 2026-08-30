"""Test-suite guards for an explicitly isolated PostgreSQL database."""

from collections.abc import Iterator

import pytest

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import DatabaseIdentityError, verify_database_identity


@pytest.fixture(scope="session", autouse=True)
def isolated_database_settings() -> Iterator[None]:
    """Keep direct ``Settings()`` calls on the explicit disposable test database."""
    try:
        settings = Settings.from_environment()
    except Exception:
        raise pytest.UsageError("Test profile/database URL validation failed.") from None
    if settings.environment != "test":
        raise pytest.UsageError("NOVALTON_ENV=test is required for database-backed tests.")
    test_database_url = settings.test_database_url
    if test_database_url is None:
        raise pytest.UsageError("NOVALTON_TEST_DATABASE_URL is required for database-backed tests.")

    import asyncio

    try:
        asyncio.run(verify_database_identity(settings))
    except DatabaseIdentityError:
        raise pytest.UsageError("Test PostgreSQL database identity validation failed.") from None

    database_field = Settings.model_fields["database_url"]
    original_default = database_field.default
    database_field.default = test_database_url
    Settings.model_rebuild(force=True)
    get_settings.cache_clear()
    try:
        yield
    finally:
        database_field.default = original_default
        Settings.model_rebuild(force=True)
        get_settings.cache_clear()
