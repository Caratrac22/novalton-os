import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.infrastructure.providers.contracts import ProviderManagedRoute
from novalton_api.infrastructure.providers.openai_compatible import OpenAICompatibleProvider
from novalton_api.infrastructure.providers.openrouter_routes import registered_openrouter_routes
from novalton_api.main import create_app
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_router import service as router_service
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class RouterApi:
    client: TestClient
    tenant_id: UUID
    workspace_id: UUID

    @property
    def url(self) -> str:
        return (
            f"/api/v1/tenants/{self.tenant_id}/workspaces/{self.workspace_id}/models/route/simulate"
        )


async def _seed_scope() -> tuple[UUID, UUID]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(ModelDefinition))
            tenant = Tenant(name="Router tenant", slug=f"router-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Router workspace", slug="router")
            session.add(workspace)
            await session.flush()
            return tenant.id, workspace.id
    finally:
        await database.dispose()


async def _cleanup(tenant_id: UUID) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(ModelDefinition))
            await session.execute(delete(Workspace).where(Workspace.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    finally:
        await database.dispose()


async def _add_models(*models: ModelDefinition) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            session.add_all(models)
    finally:
        await database.dispose()


def _model(provider_model_id: str, **changes: object) -> ModelDefinition:
    values: dict[str, object] = {
        "provider_id": "openrouter",
        "provider_model_id": provider_model_id,
        "display_name": provider_model_id,
        "status": "AVAILABLE",
        "context_window": 128_000,
        "reasoning": True,
        "coding": True,
        "tool_calling": True,
        "structured_output": True,
        "vision": True,
        "input_price_per_million": Decimal("1"),
        "output_price_per_million": Decimal("2"),
        "currency": "USD",
        "free_allowlisted": False,
    }
    values.update(changes)
    return ModelDefinition(**values)


def _request(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "required_capabilities": ["reasoning", "coding"],
        "context_tokens_estimate": 10_000,
    }
    values.update(changes)
    return values


def _virtual_route(
    provider_model_id: str,
    *,
    capabilities: frozenset[str] = frozenset({"tool_calling"}),
    context_window: int | None = 20_000,
    max_output_tokens: int | None = 512,
) -> ProviderManagedRoute:
    return ProviderManagedRoute(
        provider_id="openrouter",
        provider_model_id=provider_model_id,
        display_name=f"Virtual {provider_model_id}",
        capabilities=capabilities,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        source="test_provider_adapter",
        capability_source="test_provider_route",
    )


async def _simulate_with_routes(
    api: RouterApi,
    *,
    data: dict[str, object],
    virtual_routes: tuple[ProviderManagedRoute, ...],
) -> object:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            return await router_service.simulate(
                session,
                tenant_id=api.tenant_id,
                workspace_id=api.workspace_id,
                data=router_service.RoutingRequest(**data),
                virtual_routes=virtual_routes,
            )
    finally:
        await database.dispose()


@pytest.fixture
def api() -> Iterator[RouterApi]:
    tenant_id, workspace_id = asyncio.run(_seed_scope())
    with TestClient(create_app()) as client:
        yield RouterApi(client, tenant_id, workspace_id)
    asyncio.run(_cleanup(tenant_id))


def test_only_available_catalog_models_with_known_context_and_true_capabilities_are_eligible(
    api: RouterApi,
) -> None:
    asyncio.run(
        _add_models(
            _model("eligible"),
            _model("stale", status="STALE"),
            _model("unavailable", status="UNAVAILABLE"),
            _model("unknown-status", status="UNKNOWN"),
            _model("unknown-context", context_window=None),
            _model("short-context", context_window=9_999),
            _model("false-reasoning", reasoning=False),
            _model("unknown-coding", coding=None),
        )
    )
    response = api.client.post(api.url, json=_request())
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "SELECTED"
    assert body["eligible_candidate_count"] == 1
    assert body["selected"]["provider_model_id"] == "eligible"


@pytest.mark.parametrize(
    ("field", "capability"),
    [
        ("tool_calling_required", "tool_calling"),
        ("structured_output_required", "structured_output"),
        ("vision_required", "vision"),
    ],
)
def test_explicit_capability_requirements_reject_false_and_unknown(
    api: RouterApi, field: str, capability: str
) -> None:
    asyncio.run(
        _add_models(
            _model("true"),
            _model("false", **{capability: False}),
            _model("unknown", **{capability: None}),
        )
    )
    response = api.client.post(api.url, json=_request(**{field: True}))
    assert response.json()["eligible_candidate_count"] == 1
    assert response.json()["selected"]["provider_model_id"] == "true"


def test_cheapest_qualifying_model_wins_and_decimal_cost_is_labeled_estimate(
    api: RouterApi,
) -> None:
    asyncio.run(
        _add_models(
            _model("cheap-insufficient", reasoning=False, input_price_per_million=Decimal("0")),
            _model(
                "winner",
                input_price_per_million=Decimal("0.1234567890"),
                output_price_per_million=Decimal("0.9876543210"),
            ),
            _model("expensive", input_price_per_million=Decimal("4")),
        )
    )
    response = api.client.post(
        api.url,
        json=_request(context_tokens_estimate=1_000, expected_output_tokens=500),
    )
    selected = response.json()["selected"]
    assert selected["provider_model_id"] == "winner"
    assert selected["estimated_cost"] == {
        "amount": "0.0006172839495",
        "currency": "USD",
        "input_tokens_estimate": 1000,
        "output_tokens_estimate": 500,
        "is_estimate": True,
    }


def test_unknown_pricing_is_deterministic_but_does_not_beat_known_price(api: RouterApi) -> None:
    asyncio.run(
        _add_models(
            _model(
                "aaa-unknown",
                input_price_per_million=None,
                output_price_per_million=None,
                currency=None,
            ),
            _model("zzz-known", input_price_per_million=Decimal("9")),
        )
    )
    assert (
        api.client.post(api.url, json=_request()).json()["selected"]["provider_model_id"]
        == "zzz-known"
    )


def test_all_unknown_pricing_uses_deterministic_provider_model_identity(api: RouterApi) -> None:
    asyncio.run(
        _add_models(
            _model(
                "z-model",
                provider_id="alpha",
                input_price_per_million=None,
                output_price_per_million=None,
                currency=None,
            ),
            _model(
                "a-model",
                provider_id="alpha",
                input_price_per_million=None,
                output_price_per_million=None,
                currency=None,
            ),
        )
    )
    body = api.client.post(api.url, json=_request()).json()
    assert body["selected"]["provider_model_id"] == "a-model"
    assert "PRICING_UNKNOWN_DETERMINISTIC_SELECTION" in body["reason_codes"]
    assert "DETERMINISTIC_ID_TIE_BREAK" in body["reason_codes"]


def test_prefer_free_and_free_only_use_explicit_allowlist_not_zero_price(
    api: RouterApi,
) -> None:
    asyncio.run(
        _add_models(
            _model(
                "zero-not-free",
                input_price_per_million=Decimal("0"),
                output_price_per_million=Decimal("0"),
            ),
            _model("allowlisted", free_allowlisted=True, input_price_per_million=Decimal("5")),
        )
    )
    preferred = api.client.post(api.url, json=_request(cost_policy="PREFER_FREE")).json()
    assert preferred["selected"]["provider_model_id"] == "allowlisted"
    free_only = api.client.post(api.url, json=_request(cost_policy="FREE_ONLY")).json()
    assert free_only["eligible_candidate_count"] == 1
    assert free_only["selected"]["provider_model_id"] == "allowlisted"


def test_free_only_empty_returns_sanitized_no_suitable_taxonomy(api: RouterApi) -> None:
    asyncio.run(_add_models(_model("zero-not-free", input_price_per_million=Decimal("0"))))
    response = api.client.post(api.url, json=_request(cost_policy="FREE_ONLY"))
    assert response.status_code == 200
    assert response.json() == {
        "outcome": "NO_SUITABLE_MODEL",
        "selected": None,
        "reason_codes": ["FREE_ONLY_POOL_EMPTY"],
        "eligible_candidate_count": 0,
    }


def test_preferred_model_is_exact_advisory_and_ineligible_preference_is_rejected(
    api: RouterApi,
) -> None:
    preferred = _model("preferred", input_price_per_million=Decimal("10"))
    cheap = _model("cheap", input_price_per_million=Decimal("1"))
    bad = _model("bad", reasoning=False)
    asyncio.run(_add_models(preferred, cheap, bad))

    accepted = api.client.post(api.url, json=_request(preferred_model_id=str(preferred.id))).json()
    assert accepted["selected"]["catalog_model_id"] == str(preferred.id)
    assert "PREFERRED_MODEL_ACCEPTED" in accepted["reason_codes"]

    continued = api.client.post(api.url, json=_request(preferred_model_id=str(bad.id))).json()
    assert continued["selected"]["provider_model_id"] == "cheap"
    assert "PREFERRED_MODEL_REJECTED" in continued["reason_codes"]


def test_provider_preference_is_only_an_equal_cost_tie_break(api: RouterApi) -> None:
    asyncio.run(
        _add_models(
            _model("expensive", provider_id="preferred", input_price_per_million=Decimal("2")),
            _model("cheap", provider_id="other", input_price_per_million=Decimal("1")),
            _model("same-cost", provider_id="preferred", input_price_per_million=Decimal("1")),
        )
    )
    body = api.client.post(api.url, json=_request(preferred_provider="preferred")).json()
    assert body["selected"]["provider_model_id"] == "same-cost"
    assert "PROVIDER_PREFERENCE_APPLIED" in body["reason_codes"]


def test_provider_preference_cannot_override_hard_capability_constraint(api: RouterApi) -> None:
    asyncio.run(
        _add_models(
            _model("ineligible", provider_id="preferred", vision=False),
            _model("eligible", provider_id="other"),
        )
    )
    body = api.client.post(
        api.url,
        json=_request(preferred_provider="preferred", vision_required=True),
    ).json()
    assert body["selected"]["provider_id"] == "other"
    assert "PROVIDER_PREFERENCE_APPLIED" not in body["reason_codes"]


def test_forced_model_restricts_routing_to_exact_provider_model_pair(
    api: RouterApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    forced = Settings(model_router_force_model="other-provider::forced-model")
    monkeypatch.setattr("novalton_api.modules.model_router.service.get_settings", lambda: forced)
    asyncio.run(
        _add_models(
            _model("cheap", provider_id="openrouter", input_price_per_million=Decimal("0")),
            _model(
                "forced-model",
                provider_id="other-provider",
                input_price_per_million=Decimal("10"),
            ),
        )
    )

    body = api.client.post(api.url, json=_request()).json()

    assert body["outcome"] == "SELECTED"
    assert body["eligible_candidate_count"] == 1
    assert body["selected"]["provider_id"] == "other-provider"
    assert body["selected"]["provider_model_id"] == "forced-model"


def test_virtual_route_selects_and_unknown_forced_route_fails_closed(
    api: RouterApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = registered_openrouter_routes("openrouter")[0]

    async def simulate(forced_pair: str) -> object:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(ModelDefinition.id).where(
                            ModelDefinition.provider_id == "openrouter",
                            ModelDefinition.provider_model_id == "openrouter/free",
                        )
                    )
                    is None
                )
                monkeypatch.setattr(
                    "novalton_api.modules.model_router.service.get_settings",
                    lambda: Settings(model_router_force_model=forced_pair),
                )
                return await router_service.simulate(
                    session,
                    tenant_id=api.tenant_id,
                    workspace_id=api.workspace_id,
                    data=router_service.RoutingRequest(
                        **_request(
                            required_capabilities=[],
                            structured_output_required=True,
                        )
                    ),
                    virtual_routes=(route,),
                )
        finally:
            await database.dispose()

    selected = asyncio.run(simulate("openrouter::openrouter/free"))
    assert selected.eligible_candidate_count == 1
    assert selected.selected is not None
    assert selected.selected.catalog_model_id is None
    assert selected.selected.target_kind.value == "VIRTUAL_ROUTE"
    assert selected.selected.route_source == "provider_adapter"
    assert selected.selected.context_window == 200_000
    assert selected.selected.max_output_tokens is None
    assert selected.selected.dynamic_resolution is True
    assert "structured_output" in selected.selected.declared_capabilities

    unknown = asyncio.run(simulate("openrouter::dynamic/unknown"))
    assert unknown.outcome.value == "NO_SUITABLE_MODEL"
    assert unknown.eligible_candidate_count == 0


def test_duplicate_catalog_and_virtual_identity_uses_only_virtual_route_semantics(
    api: RouterApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A catalog row must not dilute or enrich a trusted virtual route declaration."""
    asyncio.run(
        _add_models(
            _model(
                "shared-route",
                context_window=1_000_000,
                max_output_tokens=1_000_000,
                vision=True,
                structured_output=True,
            )
        )
    )
    route = _virtual_route("shared-route")
    monkeypatch.setattr(
        "novalton_api.modules.model_router.service.get_settings",
        lambda: Settings(model_router_force_model="openrouter::shared-route"),
    )

    selected = asyncio.run(
        _simulate_with_routes(
            api,
            data=_request(
                required_capabilities=[],
                tool_calling_required=True,
                context_tokens_estimate=20_000,
            ),
            virtual_routes=(route,),
        )
    )

    assert selected.eligible_candidate_count == 1
    assert selected.selected is not None
    assert selected.selected.catalog_model_id is None
    assert selected.selected.target_kind.value == "VIRTUAL_ROUTE"
    assert selected.selected.route_source == "test_provider_adapter"
    assert selected.selected.capability_declaration_source == "test_provider_route"
    assert selected.selected.declared_capabilities == frozenset({"tool_calling"})
    assert selected.selected.context_window == 20_000
    assert selected.selected.max_output_tokens == 512

    vision_rejected = asyncio.run(
        _simulate_with_routes(
            api,
            data=_request(required_capabilities=[], vision_required=True),
            virtual_routes=(route,),
        )
    )
    assert vision_rejected.outcome.value == "NO_SUITABLE_MODEL"
    assert vision_rejected.eligible_candidate_count == 0
    assert vision_rejected.reason_codes == [router_service.RoutingReason.CAPABILITY_UNSATISFIED]


def test_unforced_routing_deduplicates_identity_but_retains_distinct_targets(
    api: RouterApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "novalton_api.modules.model_router.service.get_settings", lambda: Settings()
    )
    asyncio.run(
        _add_models(
            _model("shared-route", input_price_per_million=Decimal("1")),
            _model("distinct-catalog", input_price_per_million=Decimal("2")),
        )
    )

    result = asyncio.run(
        _simulate_with_routes(
            api,
            data=_request(required_capabilities=[], tool_calling_required=True),
            virtual_routes=(
                _virtual_route("shared-route"),
                _virtual_route("distinct-route"),
            ),
        )
    )

    assert result.eligible_candidate_count == 3
    assert result.selected is not None
    assert result.selected.provider_model_id == "distinct-catalog"
    assert result.selected.target_kind.value == "CATALOG_MODEL"


@pytest.mark.parametrize(
    ("forced_pair", "model_changes", "reason_codes"),
    [
        ("openrouter::absent", {}, ["NO_AVAILABLE_MODELS"]),
        ("openrouter::forced", {"status": "STALE"}, ["NO_AVAILABLE_MODELS"]),
        ("openrouter::forced", {"reasoning": False}, ["CAPABILITY_UNSATISFIED"]),
        ("openrouter::forced", {"structured_output": False}, ["CAPABILITY_UNSATISFIED"]),
        ("openrouter::forced", {"context_window": 9_999}, ["CONTEXT_UNSATISFIED"]),
    ],
)
def test_forced_model_still_fails_closed_through_existing_eligibility_rules(
    api: RouterApi,
    monkeypatch: pytest.MonkeyPatch,
    forced_pair: str,
    model_changes: dict[str, object],
    reason_codes: list[str],
) -> None:
    forced = Settings(model_router_force_model=forced_pair)
    monkeypatch.setattr("novalton_api.modules.model_router.service.get_settings", lambda: forced)
    asyncio.run(
        _add_models(
            _model("fallback"),
            _model("forced", **model_changes),
        )
    )

    body = api.client.post(api.url, json=_request(structured_output_required=True)).json()

    assert body == {
        "outcome": "NO_SUITABLE_MODEL",
        "selected": None,
        "reason_codes": reason_codes,
        "eligible_candidate_count": 0,
    }


def test_no_available_and_capability_no_suitable_categories_are_deterministic(
    api: RouterApi,
) -> None:
    empty = api.client.post(api.url, json=_request()).json()
    assert empty["reason_codes"] == ["NO_AVAILABLE_MODELS"]
    asyncio.run(_add_models(_model("wrong", reasoning=False)))
    rejected = api.client.post(api.url, json=_request()).json()
    assert rejected["reason_codes"] == ["CAPABILITY_UNSATISFIED"]


def test_context_no_suitable_never_relaxes_requirement(api: RouterApi) -> None:
    asyncio.run(_add_models(_model("too-short", context_window=9_999)))
    body = api.client.post(api.url, json=_request(context_tokens_estimate=10_000)).json()
    assert body["outcome"] == "NO_SUITABLE_MODEL"
    assert body["reason_codes"] == ["CONTEXT_UNSATISFIED"]


async def _side_effect_counts() -> tuple[int, int, int, int]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            values = []
            for model in (ApprovalRequest, AuditRecord, RuntimeEvent, ModelRun):
                values.append(await session.scalar(select(func.count()).select_from(model)) or 0)
            return tuple(values)  # type: ignore[return-value]
    finally:
        await database.dispose()


def test_scope_validation_no_side_effect_writes_and_no_execution_surface(
    api: RouterApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete_calls = 0

    async def forbidden_complete(*_: object, **__: object) -> None:
        nonlocal complete_calls
        complete_calls += 1
        raise AssertionError("provider complete must not be called by simulation")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", forbidden_complete)
    asyncio.run(_add_models(_model("selected")))
    before = asyncio.run(_side_effect_counts())
    assert api.client.post(api.url, json=_request()).status_code == 200
    assert asyncio.run(_side_effect_counts()) == before
    assert complete_calls == 0
    assert (
        api.client.post(
            api.url.replace(str(api.tenant_id), str(uuid4())), json=_request()
        ).status_code
        == 404
    )
    assert (
        api.client.post(
            api.url,
            json={**_request(), "provider_url": "https://attacker.invalid", "prompt": "secret"},
        ).status_code
        == 422
    )
    assert "model_runs" in ModelDefinition.metadata.tables
    assert "usage_events" not in ModelDefinition.metadata.tables
    assert "usage_events" not in ModelDefinition.metadata.tables
