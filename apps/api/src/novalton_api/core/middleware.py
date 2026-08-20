"""HTTP middleware shared across API versions."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from novalton_api.core.context import reset_correlation_id, set_correlation_id
from novalton_api.core.exceptions import unexpected_error_response

CORRELATION_ID_HEADER = "X-Correlation-ID"
_CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
logger = logging.getLogger(__name__)


def _correlation_id(headers: list[tuple[bytes, bytes]]) -> str:
    for name, value in headers:
        if name.lower() == b"x-correlation-id":
            candidate = value.decode("latin-1")
            if _CORRELATION_ID_PATTERN.fullmatch(candidate):
                return candidate
            break
    return f"req_{uuid4().hex}"


class CorrelationIdMiddleware:
    """Propagate a validated correlation ID using request-local context."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = _correlation_id(scope["headers"])
        token = set_correlation_id(correlation_id)
        started_at = perf_counter()
        status_code = 500
        response_started = False

        async def send_with_correlation_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", correlation_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_id)
        except Exception as exc:
            if response_started:
                raise
            response = unexpected_error_response(exc)
            await response(scope, receive, send_with_correlation_id)
        finally:
            logger.info(
                "HTTP request completed",
                extra={
                    "event": "http.request.completed",
                    "http_method": scope["method"],
                    "http_path": scope["path"],
                    "http_status": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )
            reset_correlation_id(token)
