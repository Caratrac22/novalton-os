"""Async PostgreSQL engine, session, metadata, and health primitives."""

import logging
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from novalton_api.core.config import Settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base and canonical application metadata."""


# Import application models after Base exists so Alembic sees their tables.
from novalton_api.modules.tenants.models import Tenant  # noqa: E402, F401
from novalton_api.modules.workspaces.models import Workspace  # noqa: E402, F401


def async_database_url(database_url: str) -> URL:
    """Return a PostgreSQL URL using the canonical async driver."""
    url = make_url(database_url)
    if url.drivername not in {"postgresql", "postgresql+asyncpg"}:
        raise ValueError("unsupported database driver")
    return url.set(drivername="postgresql+asyncpg")


class Database:
    """Own the async engine and per-request session factory."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        engine = create_async_engine(
            async_database_url(settings.database_url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=10,
        )
        return cls(engine)

    async def check_connection(self) -> bool:
        """Check PostgreSQL connectivity without exposing failure details."""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning(
                "PostgreSQL dependency check failed",
                extra={
                    "event": "database.health.unhealthy",
                    "exception_type": type(exc).__name__,
                },
            )
            return False
        return True

    async def dispose(self) -> None:
        """Close all pooled connections owned by this database instance."""
        await self.engine.dispose()
        logger.info("Database engine disposed", extra={"event": "database.disposed"})


def get_database(request: Request) -> Database:
    """Return the application-scoped database owner."""
    return request.app.state.database


async def get_async_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped session and always close it afterward."""
    database = get_database(request)
    async with database.session_factory() as session:
        yield session
