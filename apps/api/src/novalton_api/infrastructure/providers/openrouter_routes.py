"""OpenRouter-specific dynamic route declarations at the provider boundary."""

from novalton_api.infrastructure.providers.contracts import (
    ContractEnforcementGrade,
    ProviderManagedRoute,
)


def registered_openrouter_routes(provider_id: str) -> tuple[ProviderManagedRoute, ...]:
    if provider_id != "openrouter":
        return ()
    return (
        ProviderManagedRoute(
            provider_id=provider_id,
            provider_model_id="openrouter/free",
            display_name="OpenRouter Free Models Router",
            capabilities=frozenset({"tool_calling", "structured_output"}),
            capability_policy="DECLARED_GUARANTEE",
            contract_enforcement_grade=ContractEnforcementGrade.BEST_EFFORT,
            enforcement_metadata_source="openrouter_dynamic_route_policy",
            context_window=200_000,
            pricing_policy="FREE",
            free_allowlisted=True,
            dynamic_resolution=True,
            source="provider_adapter",
            capability_source="openrouter_dynamic_router",
        ),
    )
