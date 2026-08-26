"""Small static provider registry with no routing or dynamic loading."""

from collections.abc import Iterable

from novalton_api.infrastructure.providers.base import ModelProvider
from novalton_api.infrastructure.providers.contracts import ProviderManagedRoute
from novalton_api.infrastructure.providers.errors import UnknownProviderError


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

    @property
    def provider_managed_routes(self) -> tuple[ProviderManagedRoute, ...]:
        routes: list[ProviderManagedRoute] = []
        for provider in self._providers.values():
            routes.extend(getattr(provider, "provider_managed_routes", ()))
        identities = [(route.provider_id, route.provider_model_id) for route in routes]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate provider-managed route")
        return tuple(routes)
