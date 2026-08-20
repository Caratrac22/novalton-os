"""Application exceptions and deterministic HTTP error mapping."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from novalton_api.core.context import get_correlation_id

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    """A safe, expected application failure that may be shown to a client."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _error_response(*, status_code: int, code: str, message: str) -> JSONResponse:
    correlation_id = get_correlation_id()
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "correlation_id": correlation_id,
        },
    )


async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    logger.warning(
        "Application request rejected",
        extra={"event": "http.application_error", "error_code": exc.code},
    )
    return _error_response(status_code=exc.status_code, code=exc.code, message=exc.message)


async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed"
    return _error_response(status_code=exc.status_code, code="http_error", message=message)


async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return _error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
    )


def unexpected_error_response(exc: Exception) -> JSONResponse:
    """Map an unexpected failure without exposing exception details."""
    logger.error(
        "Unhandled application error",
        extra={"event": "http.unexpected_error", "exception_type": type(exc).__name__},
    )
    return _error_response(
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the shared application-to-HTTP error mappings."""
    app.add_exception_handler(ApplicationError, application_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
