"""Provider generation usage is authenticated evidence, not an invoice."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun, ProviderCostObservation
from novalton_api.modules.model_usage.provider_cost import (
    fetch_openrouter_cost,
    reconcile_openrouter_cost,
)
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


def _transport(*, generation_id="gen-123", cost=0.0015, status=200):
    def reply(request: httpx.Request):
        assert request.url.host == "openrouter.ai"
        assert request.url.params.get("id") == "gen-123"
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(status, json={"data": {"id": generation_id, "total_cost": cost}})

    return httpx.MockTransport(reply)


def test_authenticated_generation_metadata_is_bounded_and_strict():
    value = asyncio.run(
        fetch_openrouter_cost("gen-123", api_key="test-secret", transport=_transport())
    )
    assert value.amount == Decimal("0.0015000000")
    for transport in (
        _transport(generation_id="gen-other"),
        _transport(cost=-1),
        _transport(cost=None),
        _transport(status=401),
    ):
        with pytest.raises(ApplicationError):
            asyncio.run(
                fetch_openrouter_cost("gen-123", api_key="test-secret", transport=transport)
            )
    with pytest.raises(ApplicationError):
        asyncio.run(
            fetch_openrouter_cost("../other", api_key="test-secret", transport=_transport())
        )


async def _seed():
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Provider cost tenant", slug=f"cost-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Cost workspace", slug="cost")
            session.add(workspace)
            await session.flush()
            project = Project(workspace_id=workspace.id, name="Cost project", slug="cost")
            model = ModelDefinition(
                provider_id="openrouter",
                provider_model_id=f"example/model-{uuid4().hex}",
                display_name="Cost model",
                status="AVAILABLE",
                input_price_per_million=Decimal("1"),
                output_price_per_million=Decimal("1"),
                currency="USD",
                free_allowlisted=False,
            )
            session.add_all((project, model))
            await session.flush()
            run = ModelRun(
                tenant_id=tenant.id,
                workspace_id=workspace.id,
                project_id=project.id,
                model_definition_id=model.id,
                provider_id="openrouter",
                provider_model_id=model.provider_model_id,
                status="SUCCEEDED",
                provider_generation_id="gen-123",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            return tenant.id, workspace.id, project.id, model.id, run.id
    finally:
        await database.dispose()


async def _cleanup(ids):
    tenant_id, workspace_id, project_id, model_id, run_id = ids
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(
                delete(ProviderCostObservation).where(
                    ProviderCostObservation.model_run_id == run_id
                )
            )
            await session.execute(delete(ModelRun).where(ModelRun.id == run_id))
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.execute(delete(ModelDefinition).where(ModelDefinition.id == model_id))
    finally:
        await database.dispose()


@pytest.fixture
def run_ids():
    ids = asyncio.run(_seed())
    yield ids
    asyncio.run(_cleanup(ids))


def test_provider_reconciliation_serializes_competitors_and_preserves_evidence(run_ids):
    tenant_id, workspace_id, _, _, run_id = run_ids

    async def reconcile(cost):
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory.begin() as session:
                result = await reconcile_openrouter_cost(
                    session,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    model_run_id=run_id,
                    api_key="test-secret",
                    transport=_transport(cost=cost),
                )
                return result.reported_cost
        finally:
            await database.dispose()

    async def compete():
        assert await asyncio.gather(reconcile(0.0015), reconcile(0.0015)) == [
            Decimal("0.0015000000"),
            Decimal("0.0015000000"),
        ]
        with pytest.raises(ApplicationError) as error:
            await reconcile(0.002)
        assert error.value.code == "provider_cost_divergence"
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                observations = list(
                    await session.scalars(
                        select(ProviderCostObservation).where(
                            ProviderCostObservation.model_run_id == run_id
                        )
                    )
                )
                assert len(observations) == 1
                assert observations[0].reported_cost == Decimal("0.0015000000")
        finally:
            await database.dispose()

    asyncio.run(compete())
