import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError

from novalton_api.core.config import Settings
from novalton_api.core.context import reset_correlation_id, set_correlation_id
from novalton_api.core.database import Base, Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.main import create_app
from novalton_api.modules.approvals import service
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.approvals.schemas import ApprovalCreate, ApprovalStatus
from novalton_api.modules.audit import repository as audit_repository
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.policy import service as policy_service
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


async def _seed() -> tuple[Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            scopes = []
            for number in (1, 2):
                tenant = Tenant(name=f"Approval Tenant {number}", slug=f"approval-tenant-{number}")
                session.add(tenant)
                await session.flush()
                workspace = Workspace(
                    tenant_id=tenant.id,
                    name=f"Approval Workspace {number}",
                    slug=f"approval-workspace-{number}",
                )
                session.add(workspace)
                await session.flush()
                project = Project(
                    workspace_id=workspace.id,
                    name=f"Approval Project {number}",
                    slug=f"approval-project-{number}",
                    status="ACTIVE",
                )
                session.add(project)
                await session.flush()
                task = Task(project_id=project.id, title="Approval Task", status="BACKLOG")
                session.add(task)
                await session.flush()
                scopes.append(Scope(tenant.id, workspace.id, project.id, task.id))
            return scopes[0], scopes[1]
    finally:
        await database.dispose()


@pytest.fixture
def approval_scopes() -> tuple[Scope, Scope]:
    asyncio.run(_reset())
    scopes = asyncio.run(_seed())
    yield scopes
    asyncio.run(_reset())


def approval_data(scope: Scope, **changes: object) -> ApprovalCreate:
    values: dict[str, object] = {
        "action": "repository.write",
        "requester_actor_type": "agent",
        "requester_actor_id": "developer.agent",
        "resource_type": "task",
        "resource_id": scope.task_id,
        "project_id": scope.project_id,
        "task_id": scope.task_id,
    }
    values.update(changes)
    return ApprovalCreate.model_validate(values)


def evaluation(scope: Scope, **changes: object) -> PolicyEvaluationRequest:
    data = approval_data(scope, **changes)
    return PolicyEvaluationRequest(
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        action=data.action,
        actor_type=data.requester_actor_type,
        actor_id=data.requester_actor_id,
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        project_id=data.project_id,
        task_id=data.task_id,
        context=data.context,
    )


async def create_rule(session: object, scope: Scope, effect: PolicyEffect) -> PolicyRule:
    return await policy_service.create_rule(
        session,
        data=PolicyRuleCreate(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            name=f"Approval {effect.value}",
            action_pattern="repository.write",
            effect=effect,
        ),
    )


def test_approval_model_has_bounded_state_and_scope_constraints() -> None:
    table = Base.metadata.tables["approval_requests"]
    constraints = {constraint.name for constraint in table.constraints}
    assert table.c.id.primary_key
    assert not table.c.tenant_id.nullable
    assert not table.c.workspace_id.nullable
    assert table.c.requested_at.type.timezone is True
    assert table.c.decided_at.type.timezone is True
    assert isinstance(table.c.matched_rule_ids.type, JSONB)
    assert isinstance(table.c.policy_reasons.type, JSONB)
    assert {
        "ck_approval_requests_resource_pair",
        "ck_approval_requests_task_requires_project",
        "ck_approval_requests_status_value",
        "ck_approval_requests_scope_type_value",
        "ck_approval_requests_policy_effect_value",
        "ck_approval_requests_decision_state",
        "fk_approval_requests_tenant_id_tenants",
        "fk_approval_requests_workspace_id_workspaces",
        "fk_approval_requests_project_id_projects",
        "fk_approval_requests_task_id_tasks",
    }.issubset(constraints)


def test_contract_rejects_self_approval_identity_secrets_bodies_and_scope_broadening() -> None:
    scope = Scope(uuid4(), uuid4(), uuid4(), uuid4())
    for changes in (
        {"requester_actor_type": "local_user"},
        {"requester_actor_id": "sk-abcdefghijklmnop"},
        {"scope_type": "TASK"},
        {"resource_id": uuid4()},
        {"task_id": None},
        {"body": "full email body"},
        {"authorization": "Bearer credential"},
    ):
        with pytest.raises(ValidationError):
            approval_data(scope, **changes)


def test_scoped_http_routes_are_registered_without_decision_claim_bodies() -> None:
    schema = create_app().openapi()
    prefix = "/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/approvals"
    assert set(schema["paths"][prefix]) == {"get", "post"}
    assert set(schema["paths"][f"{prefix}/{{approval_id}}"]) == {"get"}
    for decision in ("approve", "reject"):
        operation = schema["paths"][f"{prefix}/{{approval_id}}/{decision}"]["post"]
        assert "requestBody" not in operation


@pytest.mark.asyncio
async def test_creation_requires_confirmation_and_records_safe_correlated_audit(
    approval_scopes: tuple[Scope, Scope],
) -> None:
    first, _ = approval_scopes
    database = Database.from_settings(Settings())
    token = set_correlation_id("req-approval-123")
    try:
        async with database.session_factory() as session:
            rule = await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            approval = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            records = list(
                await session.scalars(
                    select(AuditRecord).where(AuditRecord.action == "approval.request")
                )
            )
        assert approval.status == "PENDING"
        assert approval.scope_type == "ONE_ACTION"
        assert approval.policy_effect == "REQUIRE_CONFIRMATION"
        assert approval.matched_rule_ids == [str(rule.id)]
        assert approval.correlation_id == "req-approval-123"
        assert len(records) == 1
        assert records[0].correlation_id == "req-approval-123"
        assert records[0].metadata_json == {
            "action": "repository.write",
            "approval_id": str(approval.id),
            "matched_rule_count": 1,
            "matched_rule_ids": [str(rule.id)],
            "scope_type": "ONE_ACTION",
            "status": "PENDING",
        }
    finally:
        reset_correlation_id(token)
        await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", [PolicyEffect.ALLOW, PolicyEffect.BLOCK])
async def test_allow_or_block_cannot_create_approval(
    approval_scopes: tuple[Scope, Scope], effect: PolicyEffect
) -> None:
    first, _ = approval_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await create_rule(session, first, effect)
            with pytest.raises(ApplicationError) as error:
                await service.create_approval(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=approval_data(first),
                )
            assert error.value.code == "invalid_approval"
            assert await session.scalar(select(func.count()).select_from(ApprovalRequest)) == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected", "audit_action"),
    [("approve", "APPROVED", "approval.approve"), ("reject", "REJECTED", "approval.reject")],
)
async def test_decisions_are_human_terminal_audited_and_same_decision_idempotent(
    approval_scopes: tuple[Scope, Scope],
    decision: str,
    expected: str,
    audit_action: str,
) -> None:
    first, _ = approval_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            approval = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            decide = getattr(service, decision)
            decided = await decide(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                approval_id=approval.id,
            )
            repeated = await decide(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                approval_id=approval.id,
            )
            audit_count = await session.scalar(
                select(func.count())
                .select_from(AuditRecord)
                .where(AuditRecord.action == audit_action)
            )
        assert decided.status == expected == repeated.status
        assert decided.decision_actor_type == "local_user"
        assert decided.decision_actor_id is None
        assert decided.decided_at is not None
        assert audit_count == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_conflicting_decision_and_cross_scope_access_are_rejected(
    approval_scopes: tuple[Scope, Scope],
) -> None:
    first, second = approval_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            approval = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            approval_id = approval.id
            await service.approve(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                approval_id=approval_id,
            )
            with pytest.raises(ApplicationError) as conflict:
                await service.reject(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    approval_id=approval_id,
                )
            assert conflict.value.code == "approval_conflict"
            with pytest.raises(ApplicationError) as missing:
                await service.get_approval(
                    session,
                    tenant_id=second.tenant_id,
                    workspace_id=second.workspace_id,
                    approval_id=approval_id,
                )
            assert missing.value.code == "resource_not_found"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_exact_scope_matching_and_later_block_wins(
    approval_scopes: tuple[Scope, Scope],
) -> None:
    first, _ = approval_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            confirmation = await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            approval = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            await service.approve(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                approval_id=approval.id,
            )
            assert await service.is_approval_satisfied(
                session, approval_id=approval.id, request=evaluation(first)
            )
            assert not await service.is_approval_satisfied(
                session,
                approval_id=approval.id,
                request=evaluation(first, action="repository.delete"),
            )
            assert not await service.is_approval_satisfied(
                session,
                approval_id=approval.id,
                request=evaluation(
                    first,
                    resource_type="project",
                    resource_id=first.project_id,
                    task_id=None,
                ),
            )
            await create_rule(session, first, PolicyEffect.BLOCK)
            assert not await service.is_approval_satisfied(
                session, approval_id=approval.id, request=evaluation(first)
            )
            assert confirmation.enabled
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_list_is_bounded_ordered_and_isolated(approval_scopes: tuple[Scope, Scope]) -> None:
    first, second = approval_scopes
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            older = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            newer = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            records = await service.list_approvals(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                limit=1,
                offset=0,
                status=ApprovalStatus.PENDING,
            )
            assert [item.id for item in records] == [newer.id]
            assert newer.id != older.id
            assert (
                await service.list_approvals(
                    session,
                    tenant_id=second.tenant_id,
                    workspace_id=second.workspace_id,
                    limit=10,
                    offset=0,
                    status=None,
                )
                == []
            )
            with pytest.raises(ApplicationError):
                await service.list_approvals(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    limit=101,
                    offset=0,
                    status=None,
                )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_required_audit_failure_rolls_back_request_and_decision(
    approval_scopes: tuple[Scope, Scope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = approval_scopes
    database = Database.from_settings(Settings())

    async def fail(*args: object, **kwargs: object) -> AuditRecord:
        raise IntegrityError("statement", {}, Exception("private database detail"))

    try:
        async with database.session_factory() as session:
            await create_rule(session, first, PolicyEffect.REQUIRE_CONFIRMATION)
            monkeypatch.setattr(audit_repository, "append_record", fail)
            with pytest.raises(ApplicationError) as error:
                await service.create_approval(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    data=approval_data(first),
                )
            assert error.value.code == "audit_persistence_failed"
            assert await session.scalar(select(func.count()).select_from(ApprovalRequest)) == 0

        monkeypatch.undo()
        async with database.session_factory() as session:
            approval = await service.create_approval(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                data=approval_data(first),
            )
            approval_id = approval.id
            monkeypatch.setattr(audit_repository, "append_record", fail)
            with pytest.raises(ApplicationError) as error:
                await service.approve(
                    session,
                    tenant_id=first.tenant_id,
                    workspace_id=first.workspace_id,
                    approval_id=approval_id,
                )
            assert error.value.code == "audit_persistence_failed"
        async with database.session_factory() as session:
            stored = await session.get(ApprovalRequest, approval_id)
            assert stored is not None
            assert stored.status == "PENDING"
    finally:
        await database.dispose()
