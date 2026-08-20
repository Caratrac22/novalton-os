"""Provider-neutral catalog source boundary, separate from generation."""

from typing import Protocol, runtime_checkable

from novalton_api.infrastructure.providers.contracts import CatalogModel


@runtime_checkable
class ModelCatalogSource(Protocol):
    """An authoritative configured inventory for exactly one provider."""

    @property
    def provider_id(self) -> str: ...

    async def list_models(self) -> list[CatalogModel]: ...


class CatalogSourceRegistry:
    """Static exact-ID catalog lookup with no routing or dynamic loading."""

    def __init__(self, sources: tuple[ModelCatalogSource, ...] = ()) -> None:
        self._sources: dict[str, ModelCatalogSource] = {}
        for source in sources:
            if source.provider_id in self._sources:
                raise ValueError("duplicate provider_id")
            self._sources[source.provider_id] = source

    def get(self, provider_id: str) -> ModelCatalogSource:
        from novalton_api.infrastructure.providers.errors import UnknownProviderError

        try:
            return self._sources[provider_id]
        except KeyError:
            raise UnknownProviderError from None

    async def aclose(self) -> None:
        for source in self._sources.values():
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()
