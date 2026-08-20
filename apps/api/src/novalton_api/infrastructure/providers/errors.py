"""Sanitized normalized provider failure taxonomy."""

import asyncio
from enum import StrEnum


class ProviderFailure(StrEnum):
    AUTHENTICATION = "authentication_configuration"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    TRANSIENT = "transient_service_unavailable"
    INVALID_REQUEST = "invalid_request"
    MALFORMED_RESPONSE = "malformed_response"
    REFUSAL = "refusal_safety"
    CANCELLATION = "cancellation"
    UNKNOWN = "unknown_provider_error"


_SAFE_MESSAGES = {
    ProviderFailure.AUTHENTICATION: "Provider authentication or configuration failed",
    ProviderFailure.RATE_LIMIT: "Provider rate limit exceeded",
    ProviderFailure.TIMEOUT: "Provider request timed out",
    ProviderFailure.TRANSIENT: "Provider service is temporarily unavailable",
    ProviderFailure.INVALID_REQUEST: "Provider rejected the request or model",
    ProviderFailure.MALFORMED_RESPONSE: "Provider returned a malformed response",
    ProviderFailure.REFUSAL: "Provider refused the request for safety reasons",
    ProviderFailure.CANCELLATION: "Provider request was cancelled",
    ProviderFailure.UNKNOWN: "Provider request failed",
}


class ProviderError(Exception):
    """Failure safe to cross the provider boundary without provider payload data."""

    def __init__(self, failure: ProviderFailure, *, provider_id: str) -> None:
        self.failure = failure
        self.provider_id = provider_id
        super().__init__(_SAFE_MESSAGES[failure])


class UnknownProviderError(ProviderError):
    """Deterministic registry lookup failure."""

    def __init__(self) -> None:
        # Do not retain an untrusted lookup value on an exception that may be logged.
        super().__init__(ProviderFailure.INVALID_REQUEST, provider_id="registry")


class ProviderCancellationError(asyncio.CancelledError):
    """Normalized cancellation that retains asyncio cancellation semantics."""

    failure = ProviderFailure.CANCELLATION

    def __init__(self, *, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(_SAFE_MESSAGES[self.failure])
