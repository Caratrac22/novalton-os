"""Bounded OpenRouter-style model catalog transport and normalization."""

import asyncio
import json
import logging
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

import httpx

from novalton_api.infrastructure.providers.contracts import CatalogModel, ExecutionTargetClass
from novalton_api.infrastructure.providers.errors import (
    ProviderCancellationError,
    ProviderError,
    ProviderFailure,
)
from novalton_api.infrastructure.providers.openai_compatible import OpenAICompatibleConfig

logger = logging.getLogger(__name__)
_MILLION = Decimal(1_000_000)
_MAX_MODELS = 10_000


class OpenRouterCatalogSource:
    """Normalize OpenRouter's configured `/models` response without retaining it."""

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

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[CatalogModel]:
        """Fetch exactly once and return a fully validated normalized batch."""
        started_at = perf_counter()
        outcome = "success"
        count = 0
        try:
            if self._config.api_key is None and not self._config.base_url.startswith("http://"):
                raise ProviderError(ProviderFailure.AUTHENTICATION, provider_id=self.provider_id)
            response = await self._send()
            models = self._parse_response(response)
            count = len(models)
            return models
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
                "Provider catalog request completed",
                extra={
                    "event": "provider.catalog.completed",
                    "provider_id": self.provider_id,
                    "outcome_class": outcome,
                    "model_count": count,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )

    async def _send(self) -> httpx.Response:
        request = self._client.build_request("GET", f"{self._config.base_url}/models")
        response = await self._client.send(request, stream=True)
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
            request=request,
        )

    def _parse_response(self, response: httpx.Response) -> list[CatalogModel]:
        if response.is_error:
            raise ProviderError(
                self._classify_http_error(response.status_code), provider_id=self.provider_id
            )
        try:
            payload = json.loads(response.content)
            entries = payload["data"]
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError):
            raise ProviderError(
                ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id
            ) from None
        if not isinstance(entries, list) or len(entries) > _MAX_MODELS:
            raise ProviderError(ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id)

        normalized: list[CatalogModel] = []
        seen: set[str] = set()
        try:
            for entry in entries:
                model = self._normalize_entry(entry)
                if model.provider_model_id in seen:
                    raise ValueError("duplicate provider model")
                seen.add(model.provider_model_id)
                normalized.append(model)
        except (ValueError, TypeError, InvalidOperation):
            raise ProviderError(
                ProviderFailure.MALFORMED_RESPONSE, provider_id=self.provider_id
            ) from None
        return normalized

    def _normalize_entry(self, entry: object) -> CatalogModel:
        if not isinstance(entry, dict):
            raise ValueError("entry must be an object")
        model_id = entry.get("id")
        name = entry.get("name", model_id)
        context = entry.get("context_length")
        if context is not None and (not isinstance(context, int) or isinstance(context, bool)):
            raise ValueError("invalid context length")
        top_provider = entry.get("top_provider")
        if top_provider is None:
            top_provider = {}
        if not isinstance(top_provider, dict):
            raise ValueError("invalid top provider")
        max_output_tokens = top_provider.get("max_completion_tokens")
        if max_output_tokens is not None and (
            not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool)
        ):
            raise ValueError("invalid max completion tokens")

        supported = entry.get("supported_parameters")
        if supported is None:
            supported_set: set[str] = set()
        elif isinstance(supported, list) and all(isinstance(value, str) for value in supported):
            supported_set = set(supported)
        else:
            raise ValueError("invalid supported parameters")
        architecture = entry.get("architecture")
        if architecture is None:
            architecture = {}
        if not isinstance(architecture, dict):
            raise ValueError("invalid architecture")
        modalities = architecture.get("input_modalities")
        if modalities is None:
            modalities = []
        if not isinstance(modalities, list) or not all(
            isinstance(value, str) for value in modalities
        ):
            raise ValueError("invalid modalities")

        pricing = entry.get("pricing")
        input_price = output_price = None
        if pricing is not None:
            if not isinstance(pricing, dict):
                raise ValueError("invalid pricing")
            input_price = self._per_million(pricing["prompt"]) if "prompt" in pricing else None
            output_price = (
                self._per_million(pricing["completion"]) if "completion" in pricing else None
            )
        currency = "USD" if input_price is not None or output_price is not None else None
        return CatalogModel(
            provider_model_id=model_id,
            # This adapter is the trusted OpenRouter cloud-route declaration.
            execution_target_class=ExecutionTargetClass.REMOTE,
            display_name=name,
            context_window=context,
            max_output_tokens=max_output_tokens,
            reasoning=True if "reasoning" in supported_set else None,
            coding=None,
            tool_calling=True if {"tools", "tool_choice"} & supported_set else None,
            structured_output=(
                True if {"response_format", "structured_outputs"} & supported_set else None
            ),
            vision=True if "image" in modalities else None,
            input_price_per_million=input_price,
            output_price_per_million=output_price,
            currency=currency,
        )

    @staticmethod
    def _per_million(value: Any) -> Decimal | None:
        if not isinstance(value, str):
            raise ValueError("price must be a decimal string")
        if value == "-1":
            return None
        price = Decimal(value) * _MILLION
        if not price.is_finite() or price < 0:
            raise ValueError("invalid price")
        return price

    @staticmethod
    def _classify_http_error(status_code: int) -> ProviderFailure:
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
