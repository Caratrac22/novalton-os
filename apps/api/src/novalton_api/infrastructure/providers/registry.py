"""Small static provider registry with no routing or dynamic loading."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from novalton_api.core.config import get_settings
from novalton_api.infrastructure.providers.base import ModelProvider
from novalton_api.infrastructure.providers.contracts import (
    GenerationRequest,
    GenerationResult,
    ProviderManagedRoute,
)
from novalton_api.infrastructure.providers.errors import (
    ProviderError,
    ProviderFailure,
    UnknownProviderError,
)
from novalton_api.infrastructure.providers.openai_compatible import OpenAICompatibleProvider

if TYPE_CHECKING:
    from novalton_api.modules.financial.gateway import PaidGenerationAttempt

_LOCAL_ENDPOINTS = frozenset(
    f"http://{host}:{port}/v1" for host in ("127.0.0.1", "[::1]") for port in (1234, 11434)
)


class ProviderRegistry:
    """Exact provider ID lookup; selection remains a higher-layer concern."""

    def __init__(self, providers: Iterable[ModelProvider] = ()) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for provider in providers:
            if provider.provider_id in self._providers:
                raise ValueError("duplicate provider_id")
            self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> ModelProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise UnknownProviderError from None

    async def complete(
        self,
        provider_id: str,
        request: GenerationRequest,
        *,
        paid_attempt: "PaidGenerationAttempt | None" = None,
    ) -> GenerationResult:
        """Single application generation entry, including explicitly injected adapters.

        The default application supplies only the loopback provider. An injected
        HTTPS adapter is never invoked without a scoped financial attempt.
        Non-HTTP providers are deterministic test fixtures, unavailable in
        production; no caller-authored provider can become a network escape.
        """
        provider = self.get(provider_id)
        if type(provider) is OpenAICompatibleProvider:
            config = provider._config
            if config.base_url in _LOCAL_ENDPOINTS and config.api_key is None:
                if paid_attempt is not None:
                    raise ProviderError(ProviderFailure.INVALID_REQUEST, provider_id=provider_id)
                return await provider.complete(request)
            if paid_attempt is None:
                raise ProviderError(ProviderFailure.INVALID_REQUEST, provider_id=provider_id)
            from novalton_api.modules.financial.gateway import PaidGenerationGateway

            return await PaidGenerationGateway(provider).complete(
                paid_attempt.session,
                operator=paid_attempt.operator,
                authorization_id=paid_attempt.authorization_id,
                tenant_id=paid_attempt.tenant_id,
                workspace_id=paid_attempt.workspace_id,
                project_id=paid_attempt.project_id,
                request_id=paid_attempt.model_run_id,
                request=request,
                reserved_tokens=paid_attempt.reserved_tokens,
                estimated_exposure=paid_attempt.estimated_exposure,
                timeout_seconds=paid_attempt.timeout_seconds,
                model_run_id=paid_attempt.model_run_id,
            )
        if get_settings().environment != "test" or paid_attempt is not None:
            raise ProviderError(ProviderFailure.INVALID_REQUEST, provider_id="registry")
        return await provider.complete(request)

    @property
    def provider_managed_routes(self) -> tuple[ProviderManagedRoute, ...]:
        routes: list[ProviderManagedRoute] = []
        for provider in self._providers.values():
            routes.extend(getattr(provider, "provider_managed_routes", ()))
        identities = [(route.provider_id, route.provider_model_id) for route in routes]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate provider-managed route")
        return tuple(routes)
