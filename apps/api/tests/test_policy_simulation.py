import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.approvals import service as approvals_service
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.approvals.schemas import ApprovalCreate
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy import simulation
from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationRequest,
    PolicyRuleCreate,
    PolicySimulationRequest,
    RiskLevel,
)
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID


async def _reset() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(ApprovalRequest))
            await session.execute(delete(PolicyRule))
            await session.execute(delete(AuditRecord))
            await session.execute(delete(RuntimeEvent))
            await session.execute(delete(Task))
            await session.execute(delete(Project))
            await session.execute(delete(Workspace))
            await session.execute(delete(Tenant))
    finally:
        await database.dispose()


async def _seed() -> tuple[Scope, Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            scopes = []
            for tenant_number, workspace_number in ((1, 1), (1, 2), (2, 1)):
                slug = f"simulation-tenant-{tenant_number}"
                tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))
                if tenant is None:
                    tenant = Tenant(name=f"Tenant {tenant_number}", slug=slug)
                    session.add(tenant)
                    await session.flush()
                workspace = Workspace(
                    tenant_id=tenant.id,
                    name=f"Workspace {tenant_number}-{workspace_number}",
                    slug=f"simulation-workspace-{workspace_number}",
                )
                session.add(workspace)
                await session.flush()
                project = Project(
                    workspace_id=workspace.id,
                    name="Simulation Project",
                    slug="simulation-project",
                    status="ACTIVE",
                )
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title="Simulation Task", status="BACKLOG")
                session.add(task)
                await session.flush()
                scopes.append(Scope(tenant.id, workspace.id, project.id, task.id))
            return scopes[0], scopes[1], scopes[2]
    finally:
        await database.dispose()


@pytest.fixture
def simulation_scopes() -> tuple[Scope, Scope, Scope]:
    asyncio.run(_reset())
    scopes = asyncio.run(_seed())
    yield scopes
    asyncio.run(_reset())


def simulation_data(scope: Scope, **changes: object) -> PolicySimulationRequest:
    values: dict[str, object] = {
        "action": "repository.write",
        "actor_type": "agent",
        "actor_id": "developer.agent",
        "resource_type": "task",
        "resource_id": scope.task_id,
        "project_id": scope.project_id,
        "task_id": scope.task_id,
    }
    values.update(changes)
    return PolicySimulationRequest.model_validate(values)


def evaluation(scope: Scope, data: PolicySimulationRequest) -> PolicyEvaluationRequest:
    return PolicyEvaluationRequest(
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        **data.model_dump(),
    )


async def create_rule(
    session: object,
    scope: Scope,
    effect: PolicyEffect,
    **changes: object,
) -> PolicyRule:
    values: dict[str, object] = {
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "name": f"Simulation {effect.value}",
        "action_pattern": "repository.write",
        "effect": effect,
    }
    values.update(changes)
    return await policy_service.create_rule(session, data=PolicyRuleCreate.model_validate(values))


def test_contract_is_single_action_bounded_and_rejects_sensitive_or_caller_owned_fields() -> None:
    scope = Scope(uuid4(), uuid4(), uuid4(), uuid4())
    for changes in (
        {"actor_id": "sk-abcdefghijklmnop"},
        {"authorization": "Bearer credential"},
        {"body": "private message"},
        {"effect": "ALLOW"},
        {"precedence": ["ALLOW"]},
        {"tenant_id": scope.tenant_id},
        {"workspace_id": scope.workspace_id},
        {"context": {"arbitrary": "blob"}},
        {"action": "repository.*"},
    ):
        with pytest.raises(ValidationError):
            simulation_data(scope, **changes)


def test_scoped_http_route_has_one_bounded_request_shape() -> None:
    schema = create_app().openapi()
    path = "/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/policy/simulate"
    assert set(schema["paths"][path]) == {"post"}
    request_schema = schema["components"]["schemas"]["PolicySimulationRequest"]
    assert request_schema["additionalProperties"] is False
    assert "items" not in request_schema["properties"]


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", list(PolicyEffect))
async def test_all_effects_match_authoritative_decision_and_never_persist_side_effects(
    simulation_scopes: tuple[Scope, Scope, Scope], effect: PolicyEffect
) -> None:
    first, _, _ = simulation_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            rule = await create_rule(session, first, effect)
            before_updated_at = rule.updated_at
            data = simulation_data(first)
            direct = await policy_service.evaluate_decision(
                session, request=evaluation(first, data)
            )
            result = await simulation.simulate(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=data,
            )
            await session.refresh(rule)
            counts = {
                model.__tablename__: await session.scalar(select(func.count()).select_from(model))
                for model in (ApprovalRequest, AuditRecord, RuntimeEvent)
            }
        assert result.effect == direct.effect == effect
        assert result.matched_rule_ids == direct.matched_rule_ids == [rule.id]
        assert result.matched_rule_names == [rule.name]
        assert result.reasons == direct.reasons
        assert result.confirmation_required is (effect == PolicyEffect.REQUIRE_CONFIRMATION)
        assert result.audit_required is (effect != PolicyEffect.ALLOW)
        assert result.simulated is True
        assert result.executed is False
        assert "approval_id" not in result.model_dump()
        assert rule.updated_at == before_updated_at
        assert counts == {"approval_requests": 0, "audit_records": 0, "runtime_events": 0}
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_precedence_matching_conditions_inheritance_and_reasons_are_identical(
    simulation_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, sibling, _ = simulation_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            tenant = await create_rule(
                session,
                first,
                PolicyEffect.ALLOW_WITH_LOG,
                workspace_id=None,
                name="Tenant wildcard",
                action_pattern="repository.*",
                conditions=[
                    {
                        "field": "risk_level",
                        "operator": "in",
                        "value": ["HIGH", "CRITICAL"],
                    }
                ],
            )
            block = await create_rule(session, first, PolicyEffect.BLOCK, name="Workspace exact")
            data = simulation_data(first, context={"risk_level": RiskLevel.HIGH})
            first_result = await simulation.simulate(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=data,
            )
            repeated = await simulation.simulate(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=data,
            )
            sibling_data = simulation_data(
                sibling,
                resource_id=sibling.task_id,
                project_id=sibling.project_id,
                task_id=sibling.task_id,
                context={"risk_level": RiskLevel.HIGH},
            )
            sibling_result = await simulation.simulate(
                session,
                tenant_id=sibling.tenant_id,
                workspace_id=sibling.workspace_id,
                data=sibling_data,
            )
        expected_ids = sorted([tenant.id, block.id], key=str)
        assert first_result.effect == PolicyEffect.BLOCK
        assert first_result.matched_rule_ids == repeated.matched_rule_ids == expected_ids
        assert first_result.reasons == repeated.reasons
        assert sibling_result.effect == PolicyEffect.ALLOW_WITH_LOG
        assert sibling_result.matched_rule_ids == [tenant.id]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_no_match_and_corrupt_applicable_rule_fail_closed_like_direct_evaluation(
    simulation_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, _, _ = simulation_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            data = simulation_data(first)
            no_match = await simulation.simulate(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=data,
            )
            rule = await create_rule(session, first, PolicyEffect.ALLOW)
            await session.execute(
                update(PolicyRule)
                .where(PolicyRule.id == rule.id)
                .values(conditions_json={"python": "__import__('os')"})
            )
            corrupt = await simulation.simulate(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=data,
            )
            direct = await policy_service.evaluate_decision(
                session, request=evaluation(first, data)
            )
        assert no_match.effect == PolicyEffect.REQUIRE_CONFIRMATION
        assert no_match.reasons == ["no_matching_rule:confirmation_required"]
        assert corrupt.effect == direct.effect == PolicyEffect.BLOCK
        assert corrupt.matched_rule_names == []
        assert corrupt.reasons == direct.reasons == [f"rule:{rule.id}:invalid_fail_closed"]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_foreign_workspace_project_and_task_are_indistinguishable_not_found(
    simulation_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, sibling, other_tenant = simulation_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            attempts = (
                (other_tenant.tenant_id, first.workspace_id, simulation_data(first)),
                (
                    first.tenant_id,
                    first.workspace_id,
                    simulation_data(
                        first,
                        resource_type=None,
                        resource_id=None,
                        project_id=sibling.project_id,
                        task_id=None,
                    ),
                ),
                (
                    first.tenant_id,
                    first.workspace_id,
                    simulation_data(
                        first,
                        resource_type=None,
                        resource_id=None,
                        project_id=first.project_id,
                        task_id=sibling.task_id,
                    ),
                ),
            )
            for tenant_id, workspace_id, data in attempts:
                with pytest.raises(ApplicationError) as error:
                    await simulation.simulate(
                        session,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        data=data,
                    )
                assert (error.value.code, error.value.message) == (
                    "resource_not_found",
                    "Resource not found",
                )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_existing_approved_record_does_not_satisfy_or_change_raw_simulation(
    simulation_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, _, _ = simulation_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            data = simulation_data(first)
            approval = await approvals_service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=ApprovalCreate(
                    action=data.action,
                    requester_actor_type="agent",
                    requester_actor_id=data.actor_id,
                    resource_type=data.resource_type,
                    resource_id=data.resource_id,
                    project_id=data.project_id,
                    task_id=data.task_id,
                    context=data.context,
                ),
            )
            await approvals_service.approve(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                approval_id=approval.id,
            )
            before = {
                model.__tablename__: await session.scalar(select(func.count()).select_from(model))
                for model in (ApprovalRequest, AuditRecord, RuntimeEvent)
            }
            result = await simulation.simulate(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=data,
            )
            after = {
                model.__tablename__: await session.scalar(select(func.count()).select_from(model))
                for model in (ApprovalRequest, AuditRecord, RuntimeEvent)
            }
        assert result.effect == PolicyEffect.REQUIRE_CONFIRMATION
        assert result.confirmation_required is True
        assert before == after
    finally:
        await database.dispose()


def test_http_validation_is_sanitized_and_success_has_non_execution_marker(
    simulation_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, _, _ = simulation_scopes
    prefix = f"/api/v1/tenants/{first.tenant_id}/workspaces/{first.workspace_id}/policy/simulate"
    with TestClient(create_app()) as client:
        rejected = client.post(
            prefix,
            json={"action": "repository.write", "authorization": "Bearer private-value"},
            headers={"X-Correlation-ID": "simulation-invalid"},
        )
        accepted = client.post(
            prefix,
            json={"action": "repository.write", "context": {"risk_level": "HIGH"}},
            headers={"X-Correlation-ID": "simulation-valid"},
        )
    assert rejected.status_code == 422
    assert rejected.json() == {
        "error": {"code": "validation_error", "message": "Request validation failed"},
        "correlation_id": "simulation-invalid",
    }
    assert "private-value" not in rejected.text
    assert accepted.status_code == 200
    assert accepted.json()["simulated"] is True
    assert accepted.json()["executed"] is False
    assert "approval_id" not in accepted.json()
