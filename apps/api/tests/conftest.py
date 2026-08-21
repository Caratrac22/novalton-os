"""Test-suite guards for an explicitly isolated PostgreSQL database."""

from collections.abc import Iterator
from os import environ
from urllib.parse import urlparse

import pytest

from novalton_api.core.config import Settings, get_settings


@pytest.fixture(scope="session", autouse=True)
def isolated_database_settings() -> Iterator[None]:
    """Keep direct ``Settings()`` calls on the explicit disposable test database."""
    test_database_url = environ.get("NOVALTON_TEST_DATABASE_URL")
    if test_database_url is None:
        raise pytest.UsageError(
            "NOVALTON_TEST_DATABASE_URL must identify an isolated disposable test database"
        )
    parsed = urlparse(test_database_url)
    if not parsed.path.endswith("_test") or environ.get("DATABASE_URL") != test_database_url:
        raise pytest.UsageError(
            "DATABASE_URL and NOVALTON_TEST_DATABASE_URL must match an isolated *_test database"
        )

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
