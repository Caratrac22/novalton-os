import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings
from novalton_api.core.database import Base, Database
from novalton_api.core.limits import MAX_CATALOG_OUTPUT_TOKENS
from novalton_api.infrastructure.providers.catalog import CatalogSourceRegistry
from novalton_api.infrastructure.providers.contracts import CatalogModel, ContractEnforcementGrade
from novalton_api.infrastructure.providers.errors import ProviderError, ProviderFailure
from novalton_api.main import create_app
from novalton_api.modules.model_catalog import routes as catalog_routes
from novalton_api.modules.model_catalog import service
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


class FakeCatalogSource:
    provider_id = "openrouter"

    def __init__(self, models: list[CatalogModel]) -> None:
        self.models = models
        self.failure: ProviderFailure | None = None

    async def list_models(self) -> list[CatalogModel]:
        if self.failure is not None:
            raise ProviderError(self.failure, provider_id=self.provider_id)
        return self.models


@dataclass(frozen=True)
class CatalogApi:
    client: TestClient
    tenant_id: UUID
    workspace_id: UUID
    source: FakeCatalogSource


async def _seed_scope() -> tuple[UUID, UUID]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(ModelDefinition))
            tenant = Tenant(name="Catalog tenant", slug=f"catalog-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Catalog workspace", slug="catalog")
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
            workspace_ids = select(Workspace.id).where(Workspace.tenant_id == tenant_id)
            await session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    finally:
        await database.dispose()


@pytest.fixture
def api() -> Iterator[CatalogApi]:
    tenant_id, workspace_id = asyncio.run(_seed_scope())
    source = FakeCatalogSource([])
    app = create_app(catalog_sources=CatalogSourceRegistry((source,)))
    with TestClient(app) as client:
        yield CatalogApi(client, tenant_id, workspace_id, source)
    asyncio.run(_cleanup(tenant_id))


def _collection(api: CatalogApi) -> str:
    return f"/api/v1/tenants/{api.tenant_id}/workspaces/{api.workspace_id}/models"


def _refresh(api: CatalogApi):
    return api.client.post(f"{_collection(api)}/refresh", json={"provider_id": "openrouter"})


def _model(model_id: str, **changes: object) -> CatalogModel:
    values: dict[str, object] = {
        "provider_model_id": model_id,
        "display_name": model_id.title(),
        "context_window": 128_000,
    }
    values.update(changes)
    return CatalogModel.model_validate(values)


def test_model_catalog_metadata_has_only_i017_global_schema() -> None:
    table = Base.metadata.tables["model_definitions"]
    assert table.c.id.primary_key
    assert "tenant_id" not in table.c
    assert "workspace_id" not in table.c
    assert table.c.input_price_per_million.type.asdecimal is True
    assert not table.c.free_allowlisted.nullable
    names = {constraint.name for constraint in table.constraints}
    assert {
        "uq_model_definitions_provider_id_provider_model_id",
        "ck_model_definitions_context_window_value",
        "ck_model_definitions_input_price_non_negative",
        "ck_model_definitions_output_price_non_negative",
        "ck_model_definitions_status_value",
        "ck_model_definitions_contract_enforcement_grade",
        "ck_model_definitions_enforcement_metadata_source_length",
    }.issubset(names)
    assert "usage_events" not in Base.metadata.tables
    assert "usage_events" not in Base.metadata.tables
    max_output_constraint = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "ck_model_definitions_max_output_tokens_value"
    )
    assert str(max_output_constraint.sqltext) == (
        f"max_output_tokens IS NULL OR max_output_tokens BETWEEN 1 AND {MAX_CATALOG_OUTPUT_TOKENS}"
    )


def test_catalog_model_accepts_large_and_unknown_output_limits() -> None:
    assert _model("vendor/large", max_output_tokens=943718).max_output_tokens == 943718
    assert _model("vendor/unknown", max_output_tokens=None).max_output_tokens is None
    with pytest.raises(ValidationError):
        _model("vendor/zero", max_output_tokens=0)
    with pytest.raises(ValidationError):
        _model("vendor/negative", max_output_tokens=-1)
    with pytest.raises(ValidationError):
        _model("vendor/too-large", max_output_tokens=MAX_CATALOG_OUTPUT_TOKENS + 1)


def test_successful_refresh_upserts_idempotently_marks_missing_stale_and_lists(
    api: CatalogApi,
) -> None:
    api.source.models = [
        _model(
            "vendor/free-zero",
            display_name="Zero Cost Unknown",
            max_output_tokens=943718,
            reasoning=True,
            input_price_per_million=Decimal("0"),
            output_price_per_million=Decimal("0"),
            currency="USD",
        ),
        _model("vendor/second", context_window=None),
    ]
    first = _refresh(api)
    assert first.status_code == 200
    assert first.json()["verified_count"] == 2
    assert first.json()["stale_count"] == 0

    listed = api.client.get(_collection(api), params={"limit": 1})
    assert listed.status_code == 200
    assert listed.json()["limit"] == 1
    zero = listed.json()["items"][0]
    assert zero["provider_model_id"] == "vendor/free-zero"
    assert zero["max_output_tokens"] == 943718
    assert zero["status"] == "AVAILABLE"
    assert zero["free_allowlisted"] is False
    assert zero["coding"] is None
    assert zero["input_price_per_million"] == "0E-10"
    model_id = zero["id"]

    repeated = _refresh(api)
    assert repeated.status_code == 200
    assert repeated.json()["verified_count"] == 2
    assert len(api.client.get(_collection(api)).json()["items"]) == 2
    assert api.client.get(f"{_collection(api)}/{model_id}").status_code == 200

    api.source.models = [_model("vendor/second", display_name="Updated Name")]
    changed = _refresh(api)
    assert changed.status_code == 200
    assert changed.json()["stale_count"] == 1
    stale = api.client.get(_collection(api), params={"status": "STALE"}).json()["items"]
    assert [item["provider_model_id"] for item in stale] == ["vendor/free-zero"]
    available = api.client.get(
        _collection(api), params={"provider_id": "openrouter", "status": "AVAILABLE"}
    ).json()["items"]
    assert available[0]["display_name"] == "Updated Name"


def test_catalog_refresh_defaults_unknown_enforcement_to_conservative_best_effort(
    api: CatalogApi,
) -> None:
    api.source.models = [
        _model("vendor/structured", structured_output=True),
        _model("vendor/no-structured-output", structured_output=False),
    ]

    assert _refresh(api).status_code == 200
    by_id = {
        item["provider_model_id"]: item for item in api.client.get(_collection(api)).json()["items"]
    }

    assert by_id["vendor/structured"]["contract_enforcement_grade"] == (
        ContractEnforcementGrade.BEST_EFFORT.value
    )
    assert by_id["vendor/structured"]["enforcement_metadata_source"] == (
        "catalog_structured_output_capability"
    )
    assert by_id["vendor/no-structured-output"]["contract_enforcement_grade"] == (
        ContractEnforcementGrade.UNSUPPORTED.value
    )
    assert by_id["vendor/no-structured-output"]["enforcement_metadata_source"] == "catalog_unknown"


def test_configured_exact_free_allowlist_is_independent_of_price() -> None:
    settings = Settings(model_catalog_free_allowlist=("openrouter::vendor/explicit",))
    assert settings.model_catalog_free_allowlist_pairs == {("openrouter", "vendor/explicit")}
    assert Settings().model_catalog_free_allowlist_pairs == set()


def test_exact_configured_model_is_allowlisted_even_when_price_is_nonzero(
    api: CatalogApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.source.models = [
        _model(
            "vendor/explicit",
            input_price_per_million=Decimal("1.25"),
            output_price_per_million=Decimal("2.50"),
            currency="USD",
        )
    ]
    configured = Settings(model_catalog_free_allowlist=("openrouter::vendor/explicit",))
    monkeypatch.setattr(catalog_routes, "get_settings", lambda: configured)
    assert _refresh(api).status_code == 200
    model = api.client.get(_collection(api)).json()["items"][0]
    assert model["free_allowlisted"] is True


def test_provider_failures_and_unknown_source_do_not_corrupt_catalog(api: CatalogApi) -> None:
    api.source.models = [_model("vendor/stable")]
    assert _refresh(api).status_code == 200
    before = api.client.get(_collection(api)).json()["items"]
    for failure in (
        ProviderFailure.AUTHENTICATION,
        ProviderFailure.RATE_LIMIT,
        ProviderFailure.TIMEOUT,
        ProviderFailure.TRANSIENT,
    ):
        api.source.failure = failure
        response = _refresh(api)
        assert response.status_code == 502
        assert response.json()["error"] == {
            "code": "model_catalog_refresh_failed",
            "message": "Model catalog refresh failed",
        }
        assert api.client.get(_collection(api)).json()["items"] == before
    unknown = api.client.post(f"{_collection(api)}/refresh", json={"provider_id": "not_configured"})
    assert unknown.status_code == 502
    assert "not_configured" not in unknown.text


def test_scoping_bounds_and_unknown_model_are_sanitized(api: CatalogApi) -> None:
    assert api.client.get(_collection(api), params={"limit": 101}).status_code == 422
    assert (
        api.client.get(_collection(api).replace(str(api.tenant_id), str(uuid4()))).status_code
        == 404
    )
    missing = api.client.get(f"{_collection(api)}/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"] == {
        "code": "resource_not_found",
        "message": "Resource not found",
    }


@pytest.mark.asyncio
async def test_database_constraints_reject_duplicate_and_invalid_values() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            session.add_all(
                [
                    ModelDefinition(
                        provider_id="openrouter",
                        provider_model_id="duplicate",
                        display_name="First",
                        status="AVAILABLE",
                        free_allowlisted=False,
                    ),
                    ModelDefinition(
                        provider_id="openrouter",
                        provider_model_id="duplicate",
                        display_name="Second",
                        status="AVAILABLE",
                        free_allowlisted=False,
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
            session.add(
                ModelDefinition(
                    provider_id="openrouter",
                    provider_model_id="invalid",
                    display_name="Invalid",
                    status="AVAILABLE",
                    context_window=0,
                    input_price_per_million=Decimal("-1"),
                    currency="USD",
                    free_allowlisted=False,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_malformed_batch_rolls_back_all_rows() -> None:
    tenant_id, workspace_id = await _seed_scope()
    source = FakeCatalogSource([_model("vendor/valid")])
    registry = CatalogSourceRegistry((source,))
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await service.refresh_provider(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                provider_id="openrouter",
                sources=registry,
                free_allowlist=frozenset(),
            )
            source.models = [_model("vendor/new"), {"raw": "credential-secret"}]  # type: ignore[list-item]
            with pytest.raises(Exception, match="Model catalog refresh failed"):
                await service.refresh_provider(
                    session,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    provider_id="openrouter",
                    sources=registry,
                    free_allowlist=frozenset(),
                )
            rows = list(await session.scalars(select(ModelDefinition)))
            assert [row.provider_model_id for row in rows] == ["vendor/valid"]
            assert all("credential" not in repr(row.__dict__) for row in rows)
    finally:
        await database.dispose()
        await _cleanup(tenant_id)
