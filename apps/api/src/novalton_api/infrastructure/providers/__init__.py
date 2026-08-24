"""Provider-neutral model invocation boundary."""

from novalton_api.infrastructure.providers.base import ModelProvider
from novalton_api.infrastructure.providers.catalog import CatalogSourceRegistry, ModelCatalogSource
from novalton_api.infrastructure.providers.contracts import (
    CatalogModel,
    GenerationRequest,
    GenerationResult,
    Message,
    MessageRole,
    StructuredOutputRequest,
)
from novalton_api.infrastructure.providers.errors import ProviderError, ProviderFailure

__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "Message",
    "MessageRole",
    "StructuredOutputRequest",
    "ModelProvider",
    "CatalogModel",
    "CatalogSourceRegistry",
    "ModelCatalogSource",
    "ProviderError",
    "ProviderFailure",
]
