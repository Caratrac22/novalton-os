import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import JSONB

from novalton_api.core.config import Settings
from novalton_api.core.database import Base, Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.policy import repository, service
from novalton_api.modules.policy.models import PolicyRule
from novalton_api.modules.policy.schemas import (
    PolicyEffect,
    PolicyEvaluationRequest,
    PolicyRuleCreate,
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
            scopes: list[Scope] = []
            for tenant_number, workspace_number in ((1, 1), (1, 2), (2, 1)):
                tenant_slug = f"policy-tenant-{tenant_number}"
                tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
                if tenant is None:
                    tenant = Tenant(name=f"Tenant {tenant_number}", slug=tenant_slug)
                    session.add(tenant)
                    await session.flush()
                workspace = Workspace(
                    tenant_id=tenant.id,
                    name=f"Workspace {tenant_number}-{workspace_number}",
                    slug=f"policy-workspace-{workspace_number}",
                )
                session.add(workspace)
                await session.flush()
                project = Project(
                    workspace_id=workspace.id,
                    name="Policy Project",
                    slug="policy-project",
                    status="ACTIVE",
                )
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title="Policy Task", status="BACKLOG")
                session.add(task)
                await session.flush()
                scopes.append(Scope(tenant.id, workspace.id, project.id, task.id))
            return scopes[0], scopes[1], scopes[2]
    finally:
        await database.dispose()


@pytest.fixture
def policy_scopes() -> tuple[Scope, Scope, Scope]:
    asyncio.run(_reset())
    scopes = asyncio.run(_seed())
    yield scopes
    asyncio.run(_reset())


def rule_data(scope: Scope, **changes: object) -> PolicyRuleCreate:
    values: dict[str, object] = {
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "name": "Repository writes",
        "action_pattern": "repository.write",
        "effect": PolicyEffect.ALLOW,
    }
    values.update(changes)
    return PolicyRuleCreate.model_validate(values)


def evaluation(scope: Scope, **changes: object) -> PolicyEvaluationRequest:
    values: dict[str, object] = {
        "tenant_id": scope.tenant_id,
        "workspace_id": scope.workspace_id,
        "action": "repository.write",
        "project_id": scope.project_id,
        "task_id": scope.task_id,
    }
    values.update(changes)
    return PolicyEvaluationRequest.model_validate(values)


def test_policy_model_has_minimal_bounded_constraints() -> None:
    table = Base.metadata.tables["policy_rules"]
    constraints = {constraint.name for constraint in table.constraints}
    assert table.c.id.primary_key
    assert not table.c.tenant_id.nullable
    assert table.c.workspace_id.nullable
    assert table.c.name.type.length == 200
    assert table.c.action_pattern.type.length == 100
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True
    assert isinstance(table.c.conditions_json.type, JSONB)
    assert {
        "ck_policy_rules_name_length",
        "ck_policy_rules_action_pattern_length",
        "ck_policy_rules_effect_value",
        "ck_policy_rules_actor_type_length",
        "ck_policy_rules_resource_type_length",
        "fk_policy_rules_tenant_id_tenants",
        "fk_policy_rules_workspace_id_workspaces",
    }.issubset(constraints)


@pytest.mark.asyncio
async def test_tenant_rule_is_inherited_and_combined_with_workspace_rule(
    policy_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, sibling, _ = policy_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            tenant_rule = await service.create_rule(
                session,
                data=rule_data(
                    first,
                    workspace_id=None,
                    name="Tenant confirmation",
                    effect=PolicyEffect.REQUIRE_CONFIRMATION,
                ),
            )
            workspace_rule = await service.create_rule(
                session,
                data=rule_data(first, name="Workspace allow", effect=PolicyEffect.ALLOW),
            )
            first_result = await service.evaluate(session, request=evaluation(first))
            sibling_result = await service.evaluate(session, request=evaluation(sibling))
        assert first_result.effect == PolicyEffect.REQUIRE_CONFIRMATION
        assert set(first_result.matched_rule_ids) == {tenant_rule.id, workspace_rule.id}
        assert sibling_result.effect == PolicyEffect.REQUIRE_CONFIRMATION
        assert sibling_result.matched_rule_ids == [tenant_rule.id]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_disabled_workspace_and_cross_tenant_rules_never_apply(
    policy_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, sibling, other_tenant = policy_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await service.create_rule(
                session,
                data=rule_data(first, enabled=False, effect=PolicyEffect.BLOCK),
            )
            await service.create_rule(
                session,
                data=rule_data(sibling, effect=PolicyEffect.BLOCK),
            )
            await service.create_rule(
                session,
                data=rule_data(other_tenant, workspace_id=None, effect=PolicyEffect.BLOCK),
            )
            result = await service.evaluate(session, request=evaluation(first))
        assert result.effect == PolicyEffect.REQUIRE_CONFIRMATION
        assert result.matched_rule_ids == []
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_workspace_ownership_and_evaluation_scope_are_validated(
    policy_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, _, other_tenant = policy_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.create_rule(
                    session,
                    data=rule_data(first, tenant_id=uuid4(), workspace_id=None),
                )
            assert error.value.code == "resource_not_found"
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.create_rule(
                    session,
                    data=rule_data(first, workspace_id=other_tenant.workspace_id),
                )
            assert error.value.code == "resource_not_found"
        async with database.session_factory() as session:
            with pytest.raises(ApplicationError) as error:
                await service.evaluate(
                    session,
                    request=evaluation(first, project_id=other_tenant.project_id, task_id=None),
                )
            assert error.value.code == "resource_not_found"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_audit_is_minimal_and_only_written_when_required(
    policy_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, _, _ = policy_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            allow = await service.create_rule(session, data=rule_data(first))
            result = await service.evaluate(session, request=evaluation(first))
            assert result.effect == PolicyEffect.ALLOW
            assert await session.scalar(select(func.count()).select_from(AuditRecord)) == 0

            allow.enabled = False
            await session.commit()
            result = await service.evaluate(session, request=evaluation(first))
            records = list(await session.scalars(select(AuditRecord)))
        assert result.effect == PolicyEffect.REQUIRE_CONFIRMATION
        assert len(records) == 1
        assert records[0].action == "policy.evaluate"
        assert records[0].metadata_json == {
            "action": "repository.write",
            "final_effect": "REQUIRE_CONFIRMATION",
            "matched_rule_count": 0,
            "matched_rule_ids": [],
        }
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_repository_returns_only_enabled_effective_scope_rules(
    policy_scopes: tuple[Scope, Scope, Scope],
) -> None:
    first, sibling, _ = policy_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            tenant = await service.create_rule(
                session, data=rule_data(first, workspace_id=None, name="Tenant")
            )
            own = await service.create_rule(session, data=rule_data(first, name="Own"))
            await service.create_rule(session, data=rule_data(sibling, name="Sibling"))
            await service.create_rule(
                session, data=rule_data(first, name="Disabled", enabled=False)
            )
            rules = await repository.list_applicable_rules(
                session, tenant_id=first.tenant_id, workspace_id=first.workspace_id
            )
        assert {item.id for item in rules} == {tenant.id, own.id}
    finally:
        await database.dispose()
