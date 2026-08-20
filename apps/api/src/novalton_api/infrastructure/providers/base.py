"""Asynchronous provider protocol used by later catalog/router/agent modules."""

from typing import Protocol, runtime_checkable

from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult


@runtime_checkable
class ModelProvider(Protocol):
    """Minimal non-streaming model provider boundary for I-016."""

    @property
    def provider_id(self) -> str: ...

    async def complete(self, request: GenerationRequest) -> GenerationResult: ...
