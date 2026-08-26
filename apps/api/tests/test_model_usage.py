import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import (
    ContractEnforcementGrade,
    GenerationResult,
    QualificationSource,
)
from novalton_api.infrastructure.providers.errors import ProviderFailure
from novalton_api.main import create_app
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage import service
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.model_usage.schemas import ModelRunExecutionDiagnostics, ModelRunStart
from novalton_api.modules.projects.models import Project
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    model_id: UUID


async def _seed() -> Scope:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            tenant = Tenant(name="Usage tenant", slug=f"usage-{uuid4().hex[:8]}")
            session.add(tenant)
            await session.flush()
            workspace = Workspace(tenant_id=tenant.id, name="Usage workspace", slug="usage")
            session.add(workspace)
            await session.flush()
            project = Project(workspace_id=workspace.id, name="Usage project", slug="usage")
            model = ModelDefinition(
                provider_id="provider",
                provider_model_id=f"model-{uuid4().hex}",
                display_name="Usage model",
                status="AVAILABLE",
                input_price_per_million=Decimal("1.2500000000"),
                output_price_per_million=Decimal("2.5000000000"),
                currency="USD",
                free_allowlisted=False,
            )
            session.add_all((project, model))
            await session.flush()
            return Scope(tenant.id, workspace.id, project.id, model.id)
    finally:
        await database.dispose()


async def _cleanup(scope: Scope) -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(ModelRun).where(ModelRun.tenant_id == scope.tenant_id))
            await session.execute(delete(Project).where(Project.id == scope.project_id))
            await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
            await session.execute(delete(Tenant).where(Tenant.id == scope.tenant_id))
            await session.execute(
                delete(ModelDefinition).where(ModelDefinition.id == scope.model_id)
            )
    finally:
        await database.dispose()


async def _start(scope: Scope, **changes: object) -> ModelRun:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            values: dict[str, object] = {
                "model_definition_id": scope.model_id,
                "project_id": scope.project_id,
                "estimated_cost": Decimal("0.0100000000"),
                "currency": "USD",
            }
            values.update(changes)
            return await service.start_run(
                session,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data=ModelRunStart(**values),
            )
    finally:
        await database.dispose()


@pytest.fixture
def scope() -> Scope:
    value = asyncio.run(_seed())
    yield value
    asyncio.run(_cleanup(value))


def _result(**changes: object) -> GenerationResult:
    values: dict[str, object] = {
        "provider_id": "provider",
        "model_id": "unused",
        "content": "generated secret content",
        "input_tokens": 100,
        "output_tokens": 20,
        "provider_request_id": "req-safe_123",
        "duration_ms": 12.5,
    }
    values.update(changes)
    return GenerationResult(**values)


def test_success_captures_usage_snapshot_without_content(scope: Scope) -> None:
    run = asyncio.run(_start(scope))
    result = _result(model_id=run.provider_model_id)

    async def complete() -> ModelRun:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                return await service.mark_succeeded(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                    result=result,
                )
        finally:
            await database.dispose()

    completed = asyncio.run(complete())
    assert completed.status == "SUCCEEDED"
    assert (completed.input_tokens, completed.output_tokens, completed.total_tokens) == (
        100,
        20,
        120,
    )
    assert completed.estimated_cost == Decimal("0.0100000000")
    assert completed.actual_cost == Decimal("0.0001750000")
    assert completed.input_price_per_million_snapshot == Decimal("1.2500000000")
    assert "content" not in ModelRun.__table__.columns
    assert "metadata" not in ModelRun.__table__.columns


def test_missing_usage_stays_null_and_does_not_fabricate_actual_cost(scope: Scope) -> None:
    run = asyncio.run(_start(scope))

    async def complete() -> ModelRun:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                return await service.mark_succeeded(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                    result=_result(
                        model_id=run.provider_model_id,
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                    ),
                )
        finally:
            await database.dispose()

    completed = asyncio.run(complete())
    assert completed.input_tokens is None
    assert completed.output_tokens is None
    assert completed.total_tokens is None
    assert completed.actual_cost is None
    assert completed.estimated_cost == Decimal("0.0100000000")


def test_bounded_contract_diagnostics_are_persisted_and_exposed(scope: Scope) -> None:
    run = asyncio.run(
        _start(
            scope,
            target_structured_output_capability=True,
            contract_enforcement_grade=ContractEnforcementGrade.PROVIDER_ENFORCED,
            minimum_contract_enforcement_grade=ContractEnforcementGrade.PROVIDER_ENFORCED,
            enforcement_metadata_source="test_provider_policy",
            qualification_present=True,
            qualification_source=QualificationSource.OPERATOR_CONFIGURATION,
            upstream_provider_constraint="openai",
            provider_allow_fallbacks=False,
            provider_require_parameters=True,
            recovery_attempt_kind="CONTRACT_REPAIR",
            recovery_attempt_index=1,
        )
    )

    async def complete() -> ModelRun:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                await service.set_execution_diagnostics(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                    data=ModelRunExecutionDiagnostics(
                        contract_strategy_tier="STRICT_SCHEMA",
                        contract_fingerprint="a" * 64,
                        contextual_constraint_count=2,
                        execution_max_output_tokens=512,
                        output_budget_source="contract_complexity",
                    ),
                )
                return await service.mark_succeeded(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                    result=_result(
                        model_id=run.provider_model_id,
                        finish_reason="stop",
                        provider_resolved_model_id="provider/resolved-model",
                        upstream_provider_id="OpenAI",
                    ),
                    truncation_classification="NONE",
                )
        finally:
            await database.dispose()

    completed = asyncio.run(complete())
    assert completed.finish_reason == "stop"
    with TestClient(create_app()) as client:
        response = client.get(
            f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/model-runs/{run.id}"
        )
    assert response.status_code == 200
    body = response.json()
    fields = (
        "target_structured_output_capability",
        "contract_enforcement_grade",
        "minimum_contract_enforcement_grade",
        "enforcement_metadata_source",
        "qualification_present",
        "qualification_source",
        "upstream_provider_constraint",
        "provider_allow_fallbacks",
        "provider_require_parameters",
        "contract_strategy_tier",
        "contract_fingerprint",
        "contextual_constraint_count",
        "execution_max_output_tokens",
        "output_budget_source",
        "finish_reason",
        "truncation_classification",
        "recovery_attempt_kind",
        "recovery_attempt_index",
        "provider_resolved_model_id",
        "upstream_provider_id",
    )
    assert {key: body[key] for key in fields} == {
        "target_structured_output_capability": True,
        "contract_enforcement_grade": "PROVIDER_ENFORCED",
        "minimum_contract_enforcement_grade": "PROVIDER_ENFORCED",
        "enforcement_metadata_source": "test_provider_policy",
        "qualification_present": True,
        "qualification_source": "OPERATOR_CONFIGURATION",
        "upstream_provider_constraint": "openai",
        "provider_allow_fallbacks": False,
        "provider_require_parameters": True,
        "contract_strategy_tier": "STRICT_SCHEMA",
        "contract_fingerprint": "a" * 64,
        "contextual_constraint_count": 2,
        "execution_max_output_tokens": 512,
        "output_budget_source": "contract_complexity",
        "finish_reason": "stop",
        "truncation_classification": "NONE",
        "recovery_attempt_kind": "CONTRACT_REPAIR",
        "recovery_attempt_index": 1,
        "provider_resolved_model_id": "provider/resolved-model",
        "upstream_provider_id": "OpenAI",
    }
    assert "content" not in body
    assert "schema" not in body


def test_terminal_state_cannot_reopen_or_be_recompleted(scope: Scope) -> None:
    run = asyncio.run(_start(scope))

    async def fail_twice() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                failed = await service.mark_failed(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                    failure=ProviderFailure.TIMEOUT,
                )
                assert failed.failure_code == "timeout"
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError, match="already terminal"):
                    await service.mark_failed(
                        session,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        model_run_id=run.id,
                        failure=ProviderFailure.UNKNOWN,
                    )
        finally:
            await database.dispose()

    asyncio.run(fail_twice())


@pytest.mark.parametrize("failure", [ProviderFailure.TIMEOUT, ProviderFailure.RATE_LIMIT])
def test_failure_stores_only_normalized_safe_code(scope: Scope, failure: ProviderFailure) -> None:
    run = asyncio.run(_start(scope))

    async def fail() -> ModelRun:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                return await service.mark_failed(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                    failure=failure,
                )
        finally:
            await database.dispose()

    failed = asyncio.run(fail())
    assert failed.failure_code == failure.value
    assert failed.status == "FAILED"


def test_cancellation_is_distinct_terminal_state(scope: Scope) -> None:
    run = asyncio.run(_start(scope))

    async def cancel() -> ModelRun:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                return await service.cancel_run(
                    session,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    model_run_id=run.id,
                )
        finally:
            await database.dispose()

    cancelled = asyncio.run(cancel())
    assert (cancelled.status, cancelled.failure_code) == ("CANCELLED", "cancellation")


def test_provider_identity_and_request_id_are_strict(scope: Scope) -> None:
    run = asyncio.run(_start(scope))

    async def reject(result: GenerationResult) -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                with pytest.raises(ApplicationError):
                    await service.mark_succeeded(
                        session,
                        tenant_id=scope.tenant_id,
                        workspace_id=scope.workspace_id,
                        model_run_id=run.id,
                        result=result,
                    )
        finally:
            await database.dispose()

    asyncio.run(reject(_result(model_id="wrong-model")))
    asyncio.run(reject(_result(model_id=run.provider_model_id, provider_request_id="unsafe id")))
    asyncio.run(reject(_result(model_id=run.provider_model_id, input_tokens=1_000_000_000_001)))


def test_scoped_reads_hide_foreign_run_and_routes_are_read_only(scope: Scope) -> None:
    run = asyncio.run(_start(scope))
    with TestClient(create_app()) as client:
        base = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/model-runs"
        assert client.get(base).json()["items"][0]["id"] == str(run.id)
        assert client.get(f"{base}/{run.id}").status_code == 200
        foreign = base.replace(str(scope.tenant_id), str(uuid4()))
        assert client.get(f"{foreign}/{run.id}").status_code == 404
        assert client.post(base, json={}).status_code == 405
        assert client.get(f"{base}?limit=101").status_code == 422


def test_project_model_and_workspace_scope_validation(scope: Scope) -> None:
    with pytest.raises(ValidationError):
        ModelRunStart(
            model_definition_id=scope.model_id,
            estimated_cost=Decimal("-0.01"),
            currency="USD",
        )

    async def reject() -> None:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                for data in (
                    ModelRunStart(model_definition_id=uuid4()),
                    ModelRunStart(model_definition_id=scope.model_id, project_id=uuid4()),
                ):
                    with pytest.raises(ApplicationError) as error:
                        await service.start_run(
                            session,
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            data=data,
                        )
                    assert error.value.code == "resource_not_found"
        finally:
            await database.dispose()

    asyncio.run(reject())


def test_router_simulation_does_not_create_model_runs(scope: Scope) -> None:
    async def count() -> int:
        database = Database.from_settings(Settings())
        try:
            async with database.session_factory() as session:
                return await session.scalar(select(func.count()).select_from(ModelRun)) or 0
        finally:
            await database.dispose()

    before = asyncio.run(count())
    with TestClient(create_app()) as client:
        url = (
            f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
            "/models/route/simulate"
        )
        assert (
            client.post(
                url, json={"required_capabilities": [], "context_tokens_estimate": 1}
            ).status_code
            == 200
        )
    assert asyncio.run(count()) == before
