"""Request-local context shared by middleware, logging, and future services."""

from contextvars import ContextVar, Token

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the correlation ID for the current asynchronous context."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token[str | None]:
    """Set a correlation ID and return a token for deterministic cleanup."""
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Restore the correlation context to its previous value."""
    _correlation_id.reset(token)
