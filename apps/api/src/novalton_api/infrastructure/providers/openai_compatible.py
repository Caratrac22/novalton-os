"""Minimal non-streaming OpenAI-compatible HTTP provider adapter."""

import asyncio
import json
import logging
import re
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from novalton_api.infrastructure.providers.contracts import (
    GenerationRequest,
    GenerationResult,
    ProviderExecutionCapabilities,
    ProviderManagedRoute,
)
from novalton_api.infrastructure.providers.errors import (
    ProviderCancellationError,
    ProviderError,
    ProviderFailure,
)
from novalton_api.infrastructure.providers.urls import validate_provider_base_url

logger = logging.getLogger(__name__)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REFUSAL_MARKERS = {"content_filter", "content_policy_violation", "safety", "refusal"}


class OpenAICompatibleConfig(BaseModel):
    """Secret-safe runtime configuration for one explicitly named endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    base_url: str
    api_key: SecretStr | None = None
    connect_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    read_timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    write_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    pool_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    max_response_bytes: int = Field(default=1_048_576, ge=1_024, le=10_485_760)
    require_parameters: bool = False
    response_healing: bool = False
    provider_managed_routes: tuple[ProviderManagedRoute, ...] = ()

    def model_post_init(self, __context: Any) -> None:
        object.__setattr__(self, "base_url", validate_provider_base_url(self.base_url))


class OpenAICompatibleProvider:
    """Normalize one OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        if config.api_key is not None:
            headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"
        self._client = httpx.AsyncClient(
            transport=transport,
            headers=headers,
            timeout=httpx.Timeout(
                connect=config.connect_timeout_seconds,
                read=config.read_timeout_seconds,
                write=config.write_timeout_seconds,
                pool=config.pool_timeout_seconds,
            ),
            follow_redirects=False,
        )

    @property
    def provider_id(self) -> str:
        return self._config.provider_id

    @property
    def execution_capabilities(self) -> ProviderExecutionCapabilities:
        return ProviderExecutionCapabilities(
            require_parameters=self._config.require_parameters,
            response_healing=self._config.response_healing,
        )

    @property
    def provider_managed_routes(self) -> tuple[ProviderManagedRoute, ...]:
        return self._config.provider_managed_routes

    async def __aenter__(self) -> "OpenAICompatibleProvider":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        """Perform exactly one bounded call; cancellation is never intercepted."""
        started_at = perf_counter()
        outcome = "success"
        try:
            if self._config.api_key is None and not self._config.base_url.startswith("http://"):
                raise ProviderError(ProviderFailure.AUTHENTICATION, provider_id=self.provider_id)
            response = await self._send(request)
            result = self._parse_response(
                response,
                requested_model_id=request.model_id,
                duration_ms=(perf_counter() - started_at) * 1000,
            )
            return result
        except asyncio.CancelledError:
            outcome = ProviderFailure.CANCELLATION.value
            raise ProviderCancellationError(provider_id=self.provider_id) from None
        except ProviderError as exc:
            outcome = exc.failure.value
            raise
        except httpx.TimeoutException:
            outcome = ProviderFailure.TIMEOUT.value
            raise ProviderError(ProviderFailure.TIMEOUT, provider_id=self.provider_id) from None
        except httpx.HTTPError:
            outcome = ProviderFailure.TRANSIENT.value
            raise ProviderError(ProviderFailure.TRANSIENT, provider_id=self.provider_id) from None
        except Exception:
            outcome = ProviderFailure.UNKNOWN.value
            raise ProviderError(ProviderFailure.UNKNOWN, provider_id=self.provider_id) from None
        finally:
            logger.info(
                "Provider request completed",
                extra={
                    "event": "provider.request.completed",
                    "provider_id": self.provider_id,
                    "model_id": request.model_id,
                    "outcome_class": outcome,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )

    async def _send(self, request: GenerationRequest) -> httpx.Response:
        payload: dict[str, object] = {
            "model": request.model_id,
            "messages": [message.model_dump(mode="json") for message in request.messages],
            "stream": False,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.structured_output is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.structured_output.name,
                    "schema": request.structured_output.json_schema,
                    "strict": request.structured_output.strict,
                },
            }
        elif request.json_object is not None:
            payload["response_format"] = {"type": "json_object"}
        provider_options = request.provider_options
        if provider_options is not None and provider_options.require_parameters:
            payload["provider"] = {"require_parameters": True}
        if provider_options is not None and provider_options.response_healing:
            payload["plugins"] = [{"id": "response-healing"}]
        http_request = self._client.build_request(
            "POST",
            f"{self._config.base_url}/chat/completions",
            json=payload,
        )
        response = await self._client.send(http_request, stream=True)
        body = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._config.max_response_bytes:
                    raise ProviderError(
                        ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id
                    )
        finally:
            await response.aclose()
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(body),
            request=http_request,
        )

    def _parse_response(
        self, response: httpx.Response, *, requested_model_id: str, duration_ms: float
    ) -> GenerationResult:
        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if response.is_error:
                raise ProviderError(
                    self._classify_http_error(response.status_code, {}),
                    provider_id=self.provider_id,
                ) from None
            raise ProviderError(
                ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id
            ) from None
        if not isinstance(payload, dict):
            raise ProviderError(ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id)
        if response.is_error:
            raise ProviderError(
                self._classify_http_error(response.status_code, payload),
                provider_id=self.provider_id,
            )

        try:
            choice = payload["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(
                ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id
            ) from None
        refusal = message.get("refusal") if isinstance(message, dict) else None
        finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        if refusal or finish_reason in {"content_filter", "safety"}:
            raise ProviderError(ProviderFailure.REFUSAL, provider_id=self.provider_id)
        content = message.get("content") if isinstance(message, dict) else None
        provider_resolved_model_id = payload.get("model")
        if (
            not isinstance(content, str)
            or not content
            or (
                provider_resolved_model_id is not None
                and not isinstance(provider_resolved_model_id, str)
            )
        ):
            raise ProviderError(ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id)

        usage = payload.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise ProviderError(ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id)
        input_tokens = self._optional_token(usage.get("prompt_tokens"))
        output_tokens = self._optional_token(usage.get("completion_tokens"))
        total_tokens = self._optional_token(usage.get("total_tokens"))
        request_id = self._safe_request_id(response)
        try:
            return GenerationResult(
                provider_id=self.provider_id,
                model_id=requested_model_id,
                provider_resolved_model_id=provider_resolved_model_id,
                content=content,
                finish_reason=finish_reason if isinstance(finish_reason, str) else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                provider_request_id=request_id,
                duration_ms=duration_ms,
            )
        except ValueError:
            raise ProviderError(
                ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id
            ) from None

    def _classify_http_error(self, status_code: int, payload: dict[str, Any]) -> ProviderFailure:
        error = payload.get("error")
        if isinstance(error, dict):
            markers = {str(error.get(key, "")).casefold() for key in ("code", "type")}
            if markers & _REFUSAL_MARKERS:
                return ProviderFailure.REFUSAL
        if status_code in {401, 403}:
            return ProviderFailure.AUTHENTICATION
        if status_code == 429:
            return ProviderFailure.RATE_LIMIT
        if status_code in {408, 504}:
            return ProviderFailure.TIMEOUT
        if status_code >= 500:
            return ProviderFailure.TRANSIENT
        if status_code in {400, 404, 405, 409, 413, 415, 422}:
            return ProviderFailure.INVALID_REQUEST
        return ProviderFailure.UNKNOWN

    def _optional_token(self, value: object) -> int | None:
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ProviderError(ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id)
        return value

    @staticmethod
    def _safe_request_id(response: httpx.Response) -> str | None:
        for header in ("x-request-id", "openai-request-id"):
            value = response.headers.get(header)
            if value is not None and _SAFE_REQUEST_ID.fullmatch(value):
                return value
        return None
