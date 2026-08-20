from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.engine import make_url

from novalton_api.core.config import Settings
from novalton_api.core.database import Database, async_database_url, get_async_session


def test_async_database_url_preserves_postgres_components_without_exposing_password() -> None:
    source = "postgresql://db_user:secret-value@db.example:5432/novalton"

    result = async_database_url(source)

    assert result.drivername == "postgresql+asyncpg"
    assert result.username == "db_user"
    assert result.password == "secret-value"
    assert result.host == "db.example"
    assert "secret-value" not in str(result)


def test_database_factory_uses_bounded_pool_and_async_driver() -> None:
    database = Database.from_settings(Settings(database_url="postgresql://db.example/novalton"))

    assert make_url(str(database.engine.url)).drivername == "postgresql+asyncpg"
    assert database.session_factory.kw["expire_on_commit"] is False


@pytest.mark.asyncio
async def test_connection_failure_is_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    engine = AsyncMock()
    secret = "database-password-must-not-leak"
    engine.connect = lambda: (_ for _ in ()).throw(RuntimeError(secret))
    database = object.__new__(Database)
    database.engine = engine

    assert await database.check_connection() is False
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_session_dependency_closes_session() -> None:
    session = AsyncMock()
    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = session
    database = SimpleNamespace(session_factory=lambda: context_manager)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=database)))

    dependency = get_async_session(request)
    assert await anext(dependency) is session
    await dependency.aclose()

    context_manager.__aexit__.assert_awaited_once()
