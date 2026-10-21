"""Disposable PostgreSQL acceptance for the bounded trusted dispatcher."""

import asyncio
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_development_workflow import (
    QueueProvider,
    _cleanup,
    _create_vertical,
    _manager,
    _qa,
    _seed,
    _vertical_state,
    _worker,
)

from novalton_api.core.config import Settings, get_settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import GenerationResult
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.main import create_app
from novalton_api.modules.approvals.models import ApprovalRequest
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.durable_dispatch import repository, service
from novalton_api.modules.durable_dispatch.authority import (
    current_claim,
    require_workflow,
)
from novalton_api.modules.durable_dispatch.cost_evidence import list_cost_exposure
from novalton_api.modules.durable_dispatch.identity import (
    HumanOperator,
    WorkspaceOperatorPermission,
)
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchAttempt,
    DispatchDependency,
    TaskDispatch,
)
from novalton_api.modules.durable_dispatch.operator import (
    OperatorAuthority,
    authenticate_operator,
)
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import PolicyEffect, PolicyRuleCreate
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tools.models import ToolCall
from novalton_api.modules.workflows.models import WorkflowPlan, WorkflowRun
from novalton_api.modules.workflows.service import create_run as create_workflow_run


def db_call(operation):
    async def execute():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                return await operation(session)
        finally:
            await database.dispose()

    return asyncio.run(execute())


_TEST_OPERATOR_KEY = "mission-four-dispatch-test-credential-only"
_TEST_PERMISSIONS = (
    "activation.configure,dispatch.enqueue,dispatch.read,dispatch.cancel,dispatch.resolve"
)


def configure_operator(scope, monkeypatch):
    user_id = uuid5(NAMESPACE_URL, f"novalton-test-operator:{scope.workspace_id}")

    async def seed(session):
        await session.execute(
            insert(HumanOperator)
            .values(id=user_id, label="test-operator", active=True)
            .on_conflict_do_nothing(index_elements=[HumanOperator.id])
        )
        for permission in _TEST_PERMISSIONS.split(","):
            await session.execute(
                insert(WorkspaceOperatorPermission)
                .values(
                    user_id=user_id,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    permission=permission,
                    active=True,
                )
                .on_conflict_do_nothing()
            )
        await session.commit()

    db_call(seed)
    monkeypatch.setenv(
        "NOVALTON_DISPATCH_OPERATOR_KEY_SHA256",
        hashlib.sha256(_TEST_OPERATOR_KEY.encode()).hexdigest(),
    )
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_ID", "test-operator")
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_USER_ID", str(user_id))
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_TENANT_ID", str(scope.tenant_id))
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_WORKSPACE_ID", str(scope.workspace_id))
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_PERMISSIONS", _TEST_PERMISSIONS)
    get_settings.cache_clear()


def cleanup_operator(scope):
    async def cleanup(session):
        await session.execute(
            delete(WorkspaceOperatorPermission).where(
                WorkspaceOperatorPermission.tenant_id == scope.tenant_id
            )
        )
        await session.execute(
            delete(HumanOperator).where(
                HumanOperator.id
                == uuid5(NAMESPACE_URL, f"novalton-test-operator:{scope.workspace_id}")
            )
        )
        await session.commit()

    db_call(cleanup)


def operator_for(scope):
    actor = authenticate_operator(_TEST_OPERATOR_KEY)
    actor.require("dispatch.read", tenant_id=scope.tenant_id, workspace_id=scope.workspace_id)
    return actor


@pytest.fixture
def scope(monkeypatch):
    monkeypatch.setenv("NOVALTON_DURABLE_DISPATCH_ENABLED", "true")
    value = asyncio.run(_seed())
    configure_operator(value, monkeypatch)
    db_call(
        lambda session: service.configure_workspace(
            session,
            operator=operator_for(value),
            tenant_id=value.tenant_id,
            workspace_id=value.workspace_id,
            enabled=True,
        )
    )
    yield value

    async def cleanup(session):
        identifiers = select(TaskDispatch.id).where(TaskDispatch.tenant_id == value.tenant_id)
        await session.execute(
            delete(DispatchAttempt).where(DispatchAttempt.dispatch_id.in_(identifiers))
        )
        await session.execute(
            delete(DispatchDependency).where(DispatchDependency.tenant_id == value.tenant_id)
        )
        await session.execute(delete(TaskDispatch).where(TaskDispatch.tenant_id == value.tenant_id))
        await session.execute(
            delete(DispatchActivation).where(DispatchActivation.tenant_id == value.tenant_id)
        )
        await session.execute(
            delete(WorkspaceOperatorPermission).where(
                WorkspaceOperatorPermission.tenant_id == value.tenant_id
            )
        )
        await session.execute(
            delete(HumanOperator).where(
                HumanOperator.id
                == uuid5(NAMESPACE_URL, f"novalton-test-operator:{value.workspace_id}")
            )
        )
        await session.commit()

    try:
        db_call(cleanup)
        asyncio.run(_cleanup(value))
    finally:
        get_settings.cache_clear()


def other_task(scope):
    async def create(session):
        task = Task(project_id=scope.project_id, title="Independent durable task")
        session.add(task)
        await session.commit()
        return replace(scope, task_id=task.id)

    return db_call(create)


def enqueue(scope, provider, **values):
    body, advance = _create_vertical(scope, provider)
    data = DispatchRequest(
        workflow_run_id=UUID(body["workflow_run"]["id"]),
        request_key=uuid4().hex,
        deadline=datetime.now(UTC) + timedelta(hours=1),
        **values,
    )
    row = db_call(
        lambda session: service.enqueue(
            session,
            operator=operator_for(scope),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            data=data,
        )
    )
    return row, data, advance


def tick(scope, provider, **values):
    return db_call(
        lambda session: service.run_once(
            session,
            registry=ProviderRegistry((provider,)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            owner=uuid4(),
            **values,
        )
    )


def claim(scope):
    return db_call(
        lambda session: service.claim_next(
            session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, owner=uuid4()
        )
    )


def snapshot(scope, identifier):
    async def read(session):
        row = await session.get(TaskDispatch, identifier)
        attempts = list(
            await session.scalars(
                select(DispatchAttempt)
                .where(DispatchAttempt.dispatch_id == identifier)
                .order_by(DispatchAttempt.generation)
            )
        )
        models = list(
            await session.scalars(select(ModelRun).where(ModelRun.tenant_id == scope.tenant_id))
        )
        return row, attempts, models

    return db_call(read)


def expire(identifier, *, deadline=False):
    async def change(session):
        column = TaskDispatch.deadline if deadline else TaskDispatch.lease_expires_at
        await session.execute(
            update(TaskDispatch)
            .where(TaskDispatch.id == identifier)
            .values({column: func.clock_timestamp() - text("interval '1 second'")})
        )
        await session.commit()

    db_call(change)


def test_one_tick_reuses_advance_and_three_ticks_reach_real_qa_completion(scope):
    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    row, _, _ = enqueue(scope, provider, max_attempts=3, max_model_calls=3)
    assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, persisted.generation, persisted.model_call_count) == ("READY", 1, 1)
    assert len(attempts) == len(models) == len(provider.calls) == 1
    assert attempts[0].workflow_step_run_id is not None
    assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
    assert tick(scope, provider).outcome.value == "WORKFLOW_COMPLETED"
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, persisted.attempt_count, persisted.model_call_count) == ("DONE", 3, 3)
    assert [attempt.outcome for attempt in attempts] == ["READY", "READY", "DONE"]
    assert all(attempt.completed_at is not None for attempt in attempts)
    assert all(model.status == "SUCCEEDED" for model in models)
    assert tick(scope, provider) is None
    assert len(provider.calls) == 3

    async def task_status(session):
        return await session.scalar(select(Task.status).where(Task.id == scope.task_id))

    assert db_call(task_status) == "BACKLOG"


def test_controlled_multi_task_loop_skips_exhausted_task_across_fresh_sessions(scope):
    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    stopped, _, _ = enqueue(other_task(scope), provider, priority=50, max_attempts=0)
    active, _, _ = enqueue(scope, provider, priority=10, max_attempts=3, max_model_calls=3)
    assert [tick(scope, provider).outcome.value for _ in range(3)] == [
        "STEP_COMPLETED",
        "STEP_COMPLETED",
        "WORKFLOW_COMPLETED",
    ]
    blocked, blocked_attempts, _ = snapshot(scope, stopped.id)
    completed, attempts, models = snapshot(scope, active.id)
    assert (blocked.status, blocked.stop_reason, blocked_attempts) == (
        "BLOCKED",
        "dispatch_attempt_budget_exhausted",
        [],
    )
    assert (completed.status, len(attempts), len(models), len(provider.calls)) == ("DONE", 3, 3, 3)
    assert tick(scope, provider) is None


def test_explicit_bounded_batch_stops_cleanly_and_resumes_independent_work(scope):
    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    exhausted, _, _ = enqueue(other_task(scope), provider, priority=50, max_attempts=0)
    active, _, _ = enqueue(scope, provider, priority=10, max_attempts=3, max_model_calls=3)

    async def batch(session, stopped):
        stop = asyncio.Event()
        if stopped:
            stop.set()
        return await service.run_batch(
            async_sessionmaker(session.bind, expire_on_commit=False),
            registry=ProviderRegistry((provider,)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            max_iterations=3,
            stop=stop,
            lease_seconds=60,
        )

    assert db_call(lambda session: batch(session, True)) == []
    assert snapshot(scope, active.id)[0].attempt_count == 0
    results = db_call(lambda session: batch(session, False))
    assert [item.outcome.value for item in results] == [
        "STEP_COMPLETED",
        "STEP_COMPLETED",
        "WORKFLOW_COMPLETED",
    ]
    assert snapshot(scope, active.id)[0].status == "DONE"
    assert snapshot(scope, exhausted.id)[0].status == "BLOCKED"
    assert db_call(lambda session: batch(session, False)) == []
    assert len(provider.calls) == 3


def test_operator_credential_permissions_and_scope_fail_closed(scope, monkeypatch):
    with pytest.raises(ApplicationError) as wrong:
        authenticate_operator("x" * 40)
    assert wrong.value.code == "dispatch_operator_forbidden"
    with pytest.raises(ApplicationError):
        OperatorAuthority(
            object(), "0" * 64, "forged", uuid4(), scope.tenant_id, scope.workspace_id, frozenset()
        )
    verified = operator_for(scope)
    with pytest.raises(ApplicationError) as foreign:
        verified.require("dispatch.enqueue", tenant_id=scope.tenant_id, workspace_id=uuid4())
    assert foreign.value.status_code == 403
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_PERMISSIONS", "dispatch.read")
    get_settings.cache_clear()
    with pytest.raises(ApplicationError):
        verified.require(
            "dispatch.read", tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
        )
    reader = authenticate_operator(_TEST_OPERATOR_KEY)
    request = DispatchRequest(
        workflow_run_id=uuid4(),
        request_key=uuid4().hex,
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    with pytest.raises(ApplicationError) as denied_enqueue:
        db_call(
            lambda session: service.enqueue(
                session,
                operator=reader,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data=request,
            )
        )
    assert denied_enqueue.value.status_code == 403
    with pytest.raises(ApplicationError) as denied_cancel:
        db_call(
            lambda session: service.cancel_dispatch(
                session,
                operator=reader,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                dispatch_id=uuid4(),
            )
        )
    assert denied_cancel.value.status_code == 403
    with pytest.raises(ApplicationError) as denied_resolve:
        db_call(
            lambda session: service.resolve_blocked(
                session,
                operator=reader,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                blocked_id=uuid4(),
                data=request,
            )
        )
    assert denied_resolve.value.status_code == 403
    with pytest.raises(ApplicationError) as forbidden:
        db_call(
            lambda session: service.configure_workspace(
                session,
                operator=reader,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                enabled=False,
            )
        )
    assert forbidden.value.status_code == 403
    assert (
        db_call(
            lambda session: service.list_dispatches(
                session, operator=reader, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
        )
        == []
    )


def test_human_identity_and_workspace_grant_revoke_an_issued_capability(scope, monkeypatch):
    actor = operator_for(scope)
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_USER_ID", str(uuid4()))
    get_settings.cache_clear()
    with pytest.raises(ApplicationError):
        db_call(
            lambda session: service.list_dispatches(
                session, operator=actor, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
        )
    monkeypatch.setenv("NOVALTON_DISPATCH_OPERATOR_USER_ID", str(actor.user_id))
    get_settings.cache_clear()

    async def revoke(session):
        await session.execute(
            update(WorkspaceOperatorPermission)
            .where(
                WorkspaceOperatorPermission.user_id == actor.user_id,
                WorkspaceOperatorPermission.workspace_id == scope.workspace_id,
                WorkspaceOperatorPermission.permission == "dispatch.read",
            )
            .values(active=False, revoked_at=func.clock_timestamp())
        )
        await session.commit()

    db_call(revoke)
    with pytest.raises(ApplicationError) as denied:
        db_call(
            lambda session: service.list_dispatches(
                session, operator=actor, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
        )
    assert denied.value.status_code == 403

    async def disable_user(session):
        await session.execute(
            update(HumanOperator).where(HumanOperator.id == actor.user_id).values(active=False)
        )
        await session.commit()

    db_call(disable_user)
    with pytest.raises(ApplicationError):
        db_call(
            lambda session: service.configure_workspace(
                session,
                operator=actor,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                enabled=False,
            )
        )


def test_revocation_waits_for_inflight_human_decision_then_blocks_new_decisions(scope):
    actor = operator_for(scope)
    checked, release, revoked = threading.Event(), threading.Event(), threading.Event()

    def hold_authorized_decision():
        async def hold(session):
            await actor.require_human(
                session, "dispatch.read", tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            checked.set()
            assert await asyncio.to_thread(release.wait, 15)
            await session.commit()
            assert await asyncio.to_thread(revoked.wait, 15)
            with pytest.raises(ApplicationError):
                await actor.require_human(
                    session,
                    "dispatch.read",
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                )

        db_call(hold)

    def revoke():
        async def change(session):
            await session.execute(
                update(WorkspaceOperatorPermission)
                .where(
                    WorkspaceOperatorPermission.user_id == actor.user_id,
                    WorkspaceOperatorPermission.workspace_id == scope.workspace_id,
                    WorkspaceOperatorPermission.permission == "dispatch.read",
                )
                .values(active=False, revoked_at=func.clock_timestamp())
            )
            await session.commit()

        db_call(change)
        revoked.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_authorized_decision)
        assert checked.wait(15)
        second = executor.submit(revoke)
        assert not revoked.wait(0.2)
        release.set()
        first.result(timeout=15)
        second.result(timeout=15)
    with pytest.raises(ApplicationError) as error:
        db_call(
            lambda session: service.list_dispatches(
                session, operator=actor, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
        )
    assert error.value.status_code == 403


def test_revoked_activation_grant_stops_worker_claims_after_engaged_provider(scope):
    provider = QueueProvider([_manager(), _worker()])
    row, _, _ = enqueue(scope, provider)
    entered, released = threading.Event(), threading.Event()
    original = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await original(request)

    provider.complete = delayed
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(tick, scope, provider)
        assert entered.wait(15)
        try:

            async def revoke(session):
                await session.execute(
                    update(WorkspaceOperatorPermission)
                    .where(
                        WorkspaceOperatorPermission.user_id == operator_for(scope).user_id,
                        WorkspaceOperatorPermission.workspace_id == scope.workspace_id,
                        WorkspaceOperatorPermission.permission == "activation.configure",
                    )
                    .values(active=False, revoked_at=func.clock_timestamp())
                )
                await session.commit()

            db_call(revoke)
        finally:
            released.set()
        with pytest.raises(ApplicationError) as interrupted:
            active.result(timeout=20)
        assert interrupted.value.status_code == 403

    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, len(attempts), len(models), len(provider.calls)) == (
        "BLOCKED",
        1,
        1,
        1,
    )
    assert attempts[0].outcome == "BLOCKED"
    assert models[0].status == "SUCCEEDED"
    with pytest.raises(ApplicationError) as forbidden:
        tick(scope, provider)
    assert forbidden.value.status_code == 403
    assert snapshot(scope, row.id)[0].attempt_count == 1
    assert len(provider.calls) == 1


def test_operator_http_boundary_authenticates_human_and_rejects_cross_workspace(scope):
    base = f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/dispatch"
    with TestClient(create_app()) as client:
        assert client.get(f"{base}/requests").status_code == 401
        assert (
            client.get(
                f"{base}/requests", headers={"X-User-Id": str(operator_for(scope).user_id)}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{base}/requests", headers={"Authorization": "Bearer " + "x" * 40}
            ).status_code
            == 403
        )
        headers = {"Authorization": f"Bearer {_TEST_OPERATOR_KEY}"}
        assert client.get(f"{base}/requests", headers=headers).json() == []
        assert (
            client.get(
                f"/api/v1/tenants/{scope.tenant_id}/workspaces/{uuid4()}/dispatch/requests",
                headers=headers,
            ).status_code
            == 403
        )
        provider = QueueProvider([])
        row, _, _ = enqueue(scope, provider)
        response = client.get(f"{base}/requests", headers=headers)
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [str(row.id)]
        assert client.get(f"{base}/requests/{row.id}/attempts", headers=headers).json() == []
        assert client.get(f"{base}/requests/{row.id}/cost-evidence", headers=headers).json() == []
        cancelled = client.post(f"{base}/requests/{row.id}/cancel", headers=headers)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"


def test_operator_read_and_repeated_cancel_leave_one_audited_fence(scope):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    operator = operator_for(scope)

    async def inspect(session):
        return await service.list_dispatches(
            session, operator=operator, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
        ), await service.list_attempts(
            session,
            operator=operator,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            dispatch_id=row.id,
        )

    listed, attempts = db_call(inspect)
    assert [entry.id for entry in listed] == [row.id]
    assert attempts == []
    for _ in range(2):
        cancelled = db_call(
            lambda session: service.cancel_dispatch(
                session,
                operator=operator,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                dispatch_id=row.id,
            )
        )
        assert cancelled.status == "CANCELLED"
    assert tick(scope, provider) is None
    assert provider.calls == []

    async def audit_count(session):
        return await session.scalar(
            select(func.count())
            .select_from(AuditRecord)
            .where(
                AuditRecord.tenant_id == scope.tenant_id,
                AuditRecord.action == "dispatch.task.cancel",
                AuditRecord.actor_id == operator.actor_id,
            )
        )

    assert db_call(audit_count) == 1
    with pytest.raises(ApplicationError) as foreign:
        db_call(
            lambda session: service.list_attempts(
                session,
                operator=operator,
                tenant_id=scope.tenant_id,
                workspace_id=uuid4(),
                dispatch_id=row.id,
            )
        )
    assert foreign.value.status_code == 403


def test_resolution_requires_explicit_terminal_old_workflow_and_fresh_run(scope):
    provider = QueueProvider([])
    old, _, _ = enqueue(scope, provider, max_attempts=0)
    assert tick(scope, provider) is None

    async def fresh_run(session):
        plan_id = await session.scalar(
            select(WorkflowRun.workflow_plan_id).where(WorkflowRun.id == old.workflow_run_id)
        )
        run = await create_workflow_run(
            session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, plan_id=plan_id
        )
        return run.id

    data = DispatchRequest(
        workflow_run_id=db_call(fresh_run),
        request_key=uuid4().hex,
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    operator = operator_for(scope)

    def resolve():
        return db_call(
            lambda session: service.resolve_blocked(
                session,
                operator=operator,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                blocked_id=old.id,
                data=data,
            )
        )

    with pytest.raises(ApplicationError) as blocked:
        resolve()
    assert blocked.value.code == "dispatch_resolution_requires_terminal_old_and_fresh_run"
    db_call(
        lambda session: service.cancel_dispatch(
            session,
            operator=operator,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            dispatch_id=old.id,
        )
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: resolve(), range(2)))
    assert {result.id for result in results} == {results[0].id}
    assert results[0].workflow_run_id == data.workflow_run_id
    assert results[0].id != old.id
    assert snapshot(scope, old.id)[0].status == "CANCELLED"

    async def resolution_count(session):
        return await session.scalar(
            select(func.count())
            .select_from(AuditRecord)
            .where(
                AuditRecord.tenant_id == scope.tenant_id,
                AuditRecord.action == "dispatch.task.resolve",
            )
        )

    assert db_call(resolution_count) == 1


def test_bounded_capacity_claims_are_unique_and_lost_workers_never_replay(scope, capsys):
    provider = QueueProvider([])
    rows = [enqueue(other_task(scope), provider, priority=number % 3)[0] for number in range(18)]
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=6) as executor:
        claims = list(executor.map(lambda _: claim(scope), rows))
    claim_seconds = time.perf_counter() - started
    assert all(item is not None for item in claims)
    assert len({item.dispatch_id for item in claims}) == len(rows)
    assert {item.dispatch_id for item in claims} == {row.id for row in rows}

    async def lose_and_observe(session):
        await session.execute(
            update(TaskDispatch)
            .where(TaskDispatch.tenant_id == scope.tenant_id, TaskDispatch.status == "LEASED")
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        await session.commit()
        changed = await repository.reconcile(
            session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, limit=32
        )
        states = list(
            await session.execute(
                select(TaskDispatch.status, TaskDispatch.attempt_count, DispatchAttempt.outcome)
                .join(DispatchAttempt, DispatchAttempt.dispatch_id == TaskDispatch.id)
                .where(TaskDispatch.tenant_id == scope.tenant_id)
            )
        )
        return changed, states

    changed, states = db_call(lose_and_observe)
    assert changed == len(rows)
    assert [tuple(state) for state in states] == [("BLOCKED", 1, "BLOCKED")] * len(rows)
    assert claim(scope) is None
    assert provider.calls == []
    measurement = {
        "dispatches": len(rows),
        "workers": 6,
        "claim_seconds": round(claim_seconds, 3),
        "collisions": len(rows) - len({item.dispatch_id for item in claims}),
        "recovered_blocked": changed,
    }
    assert measurement["collisions"] == 0
    with capsys.disabled():
        print("dispatch_capacity " + json.dumps(measurement, sort_keys=True), flush=True)


@pytest.mark.parametrize("count", [50, 100, 200])
def test_sustained_claims_with_arrivals_and_uncertain_recovery(scope, capsys, count):
    """Queue-only PostgreSQL workload; it deliberately sends no model request."""

    async def seed(session, start, size):
        tasks = [
            Task(project_id=scope.project_id, title=f"Load task {i}")
            for i in range(start, start + size)
        ]
        session.add_all(tasks)
        await session.flush()
        plans = [
            WorkflowPlan(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                task_id=task.id,
                version=1,
                title="Synthetic claim-only plan",
            )
            for task in tasks
        ]
        session.add_all(plans)
        await session.flush()
        runs = [
            WorkflowRun(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                task_id=task.id,
                workflow_plan_id=plan.id,
                plan_version=1,
                status="CREATED",
            )
            for task, plan in zip(tasks, plans, strict=True)
        ]
        session.add_all(runs)
        await session.flush()
        session.add_all(
            [
                TaskDispatch(
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    project_id=scope.project_id,
                    task_id=task.id,
                    workflow_run_id=run.id,
                    request_key=f"load-{count}-{i}",
                    input_fingerprint="0" * 64,
                    priority=i % 3 - 1,
                    eligible_at=datetime.now(UTC),
                    deadline=datetime.now(UTC) + timedelta(hours=1),
                    status="READY",
                    max_attempts=1,
                    max_model_calls=1,
                )
                for i, (task, run) in enumerate(zip(tasks, runs, strict=True), start=start)
            ]
        )
        await session.commit()

    db_call(lambda session: seed(session, 0, count - 10))
    latencies: list[float] = []
    identifiers: list[UUID] = []
    guard = threading.Lock()
    errors: list[str] = []

    def worker():
        async def run():
            database = Database.from_settings(Settings.from_environment())
            try:
                until = time.monotonic() + 90
                while time.monotonic() < until:
                    with guard:
                        if len(identifiers) == count:
                            return
                    started = time.perf_counter()
                    async with database.session_factory() as session:
                        item = await service.claim_next(
                            session,
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            owner=uuid4(),
                        )
                    if item is None:
                        await asyncio.sleep(0.01)
                        continue
                    with guard:
                        identifiers.append(item.dispatch_id)
                        latencies.append(time.perf_counter() - started)
                raise TimeoutError("bounded claim workload did not complete")
            finally:
                await database.dispose()

        try:
            asyncio.run(run())
        except Exception as exc:
            with guard:
                errors.append(type(exc).__name__)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(worker) for _ in range(6)]
        time.sleep(0.02)
        db_call(lambda session: seed(session, count - 10, 10))
        for future in futures:
            future.result(timeout=100)
    elapsed = time.perf_counter() - started
    assert errors == []
    assert len(identifiers) == len(set(identifiers)) == count

    async def expire_and_reconcile(session, only_half):
        selected = identifiers[: count // 2] if only_half else identifiers
        await session.execute(
            update(TaskDispatch)
            .where(TaskDispatch.id.in_(selected), TaskDispatch.status == "LEASED")
            .values(lease_expires_at=func.clock_timestamp() - text("interval '1 second'"))
        )
        await session.commit()
        changed = 0
        for _ in range(20):
            changed += await repository.reconcile(
                session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
        return changed

    first = db_call(lambda session: expire_and_reconcile(session, True))
    assert first == count // 2
    second = db_call(lambda session: expire_and_reconcile(session, False))
    assert second == count - first

    async def evidence(session):
        return list(
            await session.execute(
                select(TaskDispatch.status, TaskDispatch.attempt_count, DispatchAttempt.outcome)
                .join(DispatchAttempt, DispatchAttempt.dispatch_id == TaskDispatch.id)
                .where(TaskDispatch.tenant_id == scope.tenant_id)
            )
        )

    assert [tuple(row) for row in db_call(evidence)] == [("BLOCKED", 1, "BLOCKED")] * count
    assert claim(scope) is None
    ordered = sorted(latencies)

    def percentile(p):
        return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))] * 1000, 2)

    measurement = {
        "tasks": count,
        "workers": 6,
        "claim_elapsed_seconds": round(elapsed, 3),
        "claim_per_second": round(count / elapsed, 2),
        "claim_p50_ms": percentile(0.50),
        "claim_p95_ms": percentile(0.95),
        "claim_p99_ms": percentile(0.99),
        "collisions": count - len(set(identifiers)),
        "postgres_errors": len(errors),
        "uncertain_blocked": first + second,
    }
    with capsys.disabled():
        print("dispatch_sustained " + json.dumps(measurement, sort_keys=True), flush=True)


def test_priority_aging_bounds_starvation_against_new_high_priority_work(scope):
    provider = QueueProvider([])
    low, _, _ = enqueue(other_task(scope), provider, priority=-100)
    high, _, _ = enqueue(other_task(scope), provider, priority=100)
    first = claim(scope)
    assert first.dispatch_id == high.id
    # Expired uncertain ownership remains BLOCKED; fairness never transfers it.
    expire(high.id)
    assert claim(scope).dispatch_id == low.id
    expire(low.id)
    assert claim(scope) is None

    older, _, _ = enqueue(other_task(scope), provider, priority=-100)
    newer, _, _ = enqueue(other_task(scope), provider, priority=100)

    async def age(session):
        await session.execute(
            update(TaskDispatch)
            .where(TaskDispatch.id == older.id)
            .values(created_at=func.clock_timestamp() - text("interval '1001 seconds'"))
        )
        await session.commit()

    db_call(age)
    assert claim(scope).dispatch_id == older.id
    assert claim(scope).dispatch_id == newer.id


def test_one_iteration_heartbeat_renews_using_an_independent_session(scope):
    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    entered, released = threading.Event(), threading.Event()
    original = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await original(request)

    provider.complete = delayed

    async def controlled(session):
        return await service.run_once(
            session,
            registry=ProviderRegistry((provider,)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            owner=uuid4(),
            lease_seconds=60,
            heartbeat_session_factory=async_sessionmaker(session.bind, expire_on_commit=False),
            heartbeat_interval_seconds=0.05,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(db_call, controlled)
        assert entered.wait(15)
        try:

            async def shorten(session):
                await session.execute(
                    update(TaskDispatch)
                    .where(TaskDispatch.id == row.id)
                    .values(lease_expires_at=func.clock_timestamp() + text("interval '1 second'"))
                )
                await session.commit()

            db_call(shorten)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                lease = db_call(
                    lambda session: session.scalar(
                        select(TaskDispatch.lease_expires_at).where(TaskDispatch.id == row.id)
                    )
                )
                if lease is not None and (lease - datetime.now(UTC)).total_seconds() > 30:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("controlled heartbeat did not renew the lease")
        finally:
            released.set()
        assert future.result(timeout=20).outcome.value == "STEP_COMPLETED"
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, len(attempts), len(models), len(provider.calls)) == ("READY", 1, 1, 1)


def test_lost_heartbeat_fences_late_provider_without_replay(scope, monkeypatch):
    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    entered, lost, released = threading.Event(), threading.Event(), threading.Event()
    original = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await original(request)

    async def heartbeat_failed(session, claimed, *, lease_seconds=3600):
        assert await asyncio.to_thread(entered.wait, 10)
        lost.set()
        return False

    provider.complete = delayed
    monkeypatch.setattr(repository, "heartbeat", heartbeat_failed)

    async def controlled(session):
        return await service.run_once(
            session,
            registry=ProviderRegistry((provider,)),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            owner=uuid4(),
            lease_seconds=60,
            heartbeat_session_factory=async_sessionmaker(session.bind, expire_on_commit=False),
            heartbeat_interval_seconds=0.05,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(db_call, controlled)
        assert entered.wait(15)
        assert lost.wait(10)
        released.set()
        with pytest.raises(ApplicationError) as failure:
            future.result(timeout=20)
    assert failure.value.code == "dispatch_claim_lost"
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "LEASED"
    assert attempts[0].completed_at is None
    assert models[0].status == "SUCCEEDED"
    expire(row.id)
    assert tick(scope, provider) is None
    assert snapshot(scope, row.id)[0].status == "BLOCKED"
    assert len(provider.calls) == 1


def test_enqueue_idempotency_is_atomic_and_conflicting_bindings_fail(scope):
    provider = QueueProvider([])
    row, data, _ = enqueue(scope, provider)

    def repeat():
        return db_call(
            lambda session: service.enqueue(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data=data,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        repeated = list(executor.map(lambda _: repeat(), range(2)))
    assert {value.id for value in repeated} == {row.id}
    for changed in (
        data.model_copy(update={"priority": 1}),
        data.model_copy(update={"request_key": uuid4().hex}),
    ):
        with pytest.raises(ApplicationError) as error:
            db_call(
                lambda session, changed=changed: service.enqueue(
                    session,
                    operator=operator_for(scope),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    data=changed,
                )
            )
        assert error.value.code in {"dispatch_request_conflict", "dispatch_binding_conflict"}
    assert provider.calls == []


def test_two_claimers_get_one_generation_and_one_attempt(scope):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    barrier = threading.Barrier(2)

    def compete():
        barrier.wait(timeout=10)
        return claim(scope)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=15) for future in [executor.submit(compete) for _ in range(2)]
        ]
    assert len([value for value in results if value is not None]) == 1
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, persisted.generation) == ("LEASED", 1)
    assert len(attempts) == 1
    assert models == []


def test_two_ticks_do_not_overlap_provider_execution(scope):
    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    entered, released = threading.Event(), threading.Event()
    original = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await original(request)

    provider.complete = delayed
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(tick, scope, provider)
        assert entered.wait(15)
        try:
            second = executor.submit(tick, scope, provider)
            assert second.result(timeout=15) is None
        finally:
            released.set()
        assert first.result(timeout=15).outcome.value == "STEP_COMPLETED"
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "READY"
    assert len(attempts) == len(models) == len(provider.calls) == 1


def test_skip_locked_claim_can_select_an_independent_lower_priority_task(scope):
    provider = QueueProvider([])
    first, _, _ = enqueue(scope, provider, priority=100)
    second, _, _ = enqueue(other_task(scope), provider, priority=-100)
    entered, released = threading.Event(), threading.Event()

    def lock_first():
        async def hold(session):
            await session.scalar(
                select(TaskDispatch).where(TaskDispatch.id == first.id).with_for_update()
            )
            entered.set()
            assert await asyncio.to_thread(released.wait, 15)
            await session.rollback()

        db_call(hold)

    with ThreadPoolExecutor(max_workers=1) as executor:
        held = executor.submit(lock_first)
        assert entered.wait(15)
        try:
            claimed = claim(scope)
            assert claimed.dispatch_id == second.id
        finally:
            released.set()
        held.result(timeout=15)


def test_dependencies_and_priorities_wait_for_persisted_completion(scope):
    provider = QueueProvider([_manager(), _worker(), _qa("PASS")])
    prerequisite, _, _ = enqueue(scope, provider, priority=-50)
    dependent, _, _ = enqueue(
        other_task(scope), provider, priority=100, dependencies=(prerequisite.id,)
    )
    independent, _, _ = enqueue(other_task(scope), provider, priority=0)
    chosen = claim(scope)
    assert chosen.dispatch_id == independent.id
    assert db_call(lambda session: repository.finish(session, chosen))
    for _ in range(3):
        tick(scope, provider)
    assert snapshot(scope, prerequisite.id)[0].status == "DONE"
    assert claim(scope).dispatch_id == dependent.id


def test_failed_dependency_does_not_block_an_independent_task(scope):
    provider = QueueProvider([_manager()])
    prerequisite, _, _ = enqueue(scope, provider, max_model_calls=0)
    dependent, _, _ = enqueue(
        other_task(scope), provider, priority=100, dependencies=(prerequisite.id,)
    )
    independent, _, _ = enqueue(other_task(scope), provider, priority=-100)
    assert tick(scope, provider).workflow_run_id == independent.workflow_run_id
    assert snapshot(scope, dependent.id)[0].stop_reason == "dispatch_dependency_blocked"
    assert len(provider.calls) == 1


def test_claim_restart_before_advance_is_blocked_without_replay(scope):
    provider = QueueProvider([])
    row, _, advance = enqueue(scope, provider)
    old = claim(scope)
    assert db_call(lambda session: repository.heartbeat(session, old))
    expire(row.id)
    assert tick(scope, provider) is None
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "BLOCKED"
    assert persisted.stop_reason == "dispatch_lease_expired"
    assert attempts[0].outcome == "BLOCKED"
    assert not db_call(lambda session: repository.heartbeat(session, old))
    assert not db_call(lambda session: repository.finish(session, old))
    assert models == provider.calls == []
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        assert client.post(advance).status_code == 409


def test_crash_after_model_reservation_keeps_uncertain_evidence_and_never_replays(scope):
    class WorkerLost(BaseException):
        pass

    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)

    async def lost(request):
        provider.calls.append(request)
        raise WorkerLost()

    provider.complete = lost
    with pytest.raises(WorkerLost):
        tick(scope, provider)
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "LEASED"
    assert attempts[0].completed_at is None
    assert attempts[0].workflow_step_run_id is not None
    recorded_step = attempts[0].workflow_step_run_id
    assert len(models) == 1 and models[0].status == "RUNNING"
    exposure = db_call(
        lambda session: list_cost_exposure(
            session,
            operator=operator_for(scope),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            dispatch_id=row.id,
        )
    )
    assert len(exposure) == 1
    assert exposure[0].classification == "EXTERNAL_OUTCOME_UNKNOWN"
    assert exposure[0].observed_cost is None
    assert current_claim.get() is None
    expire(row.id)
    assert tick(scope, provider) is None
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "BLOCKED"
    assert attempts[0].workflow_step_run_id == recorded_step
    assert models[0].status == "RUNNING"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("revocation", ["lease", "deadline", "activation"])
def test_late_provider_after_revocation_keeps_usage_but_has_no_proposal_authority(
    scope, revocation
):
    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    entered, released = threading.Event(), threading.Event()
    original = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await original(request)

    provider.complete = delayed
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(tick, scope, provider)
        assert entered.wait(15)
        try:
            if revocation == "activation":
                for enabled in (False, True):
                    db_call(
                        lambda session, enabled=enabled: service.configure_workspace(
                            session,
                            operator=operator_for(scope),
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            enabled=enabled,
                        )
                    )
            else:
                expire(row.id, deadline=revocation == "deadline")
            db_call(
                lambda session: repository.reconcile(
                    session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
                )
            )
        finally:
            released.set()
        with pytest.raises(ApplicationError):
            future.result(timeout=20)
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "BLOCKED"
    assert len(attempts) == len(models) == len(provider.calls) == 1
    assert models[0].status == "SUCCEEDED"
    state = asyncio.run(_vertical_state(scope, row.workflow_run_id))
    assert len(state["handoffs"]) == 1
    assert state["run"].status in {"RUNNING", "FAILED"}
    assert tick(scope, provider) is None
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("max_attempts", "dispatch_attempt_budget_exhausted"),
        ("max_model_calls", "dispatch_model_budget_exhausted"),
        ("deadline", "dispatch_deadline_exhausted"),
    ],
)
def test_zero_budget_or_deadline_never_reserves_a_provider_or_tool(scope, field, reason):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider, **({field: 0} if field != "deadline" else {}))
    if field == "deadline":
        expire(row.id, deadline=True)
    assert tick(scope, provider) is None
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, persisted.stop_reason) == ("BLOCKED", reason)
    assert attempts == models == provider.calls == []

    async def tools(session):
        return await session.scalar(
            select(func.count()).select_from(ToolCall).where(ToolCall.tenant_id == scope.tenant_id)
        )

    assert db_call(tools) == 0


def test_truncation_recovery_cannot_exceed_the_persisted_model_budget(scope):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider, max_model_calls=1)

    async def truncated(request):
        provider.calls.append(request)
        return GenerationResult(
            provider_id="mock",
            model_id=request.model_id,
            content='{"status":',
            finish_reason="length",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )

    provider.complete = truncated
    result = tick(scope, provider)
    assert result.outcome.value == "WORKFLOW_FAILED"
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, persisted.model_call_count) == ("BLOCKED", 1)
    assert len(attempts) == len(models) == len(provider.calls) == 1
    assert tick(scope, provider) is None


@pytest.mark.parametrize("allow_unknown_cost", [False, True])
def test_unknown_model_cost_requires_explicit_operator_policy(scope, allow_unknown_cost):
    provider = QueueProvider([_manager()])

    async def unknown(session):
        await session.execute(
            update(ModelDefinition)
            .where(ModelDefinition.id == scope.model_id)
            .values(input_price_per_million=None, output_price_per_million=None, currency=None)
        )
        await session.commit()

    db_call(unknown)
    row, _, _ = enqueue(scope, provider, allow_unknown_cost=allow_unknown_cost)
    result = tick(scope, provider)
    persisted, _, models = snapshot(scope, row.id)
    if allow_unknown_cost:
        assert result.outcome.value == "STEP_COMPLETED"
        assert len(models) == len(provider.calls) == persisted.model_call_count == 1
        assert models[0].actual_cost is None
        exposure = db_call(
            lambda session: list_cost_exposure(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                dispatch_id=row.id,
            )
        )
        assert [item.classification for item in exposure] == ["ACTUAL_COST_UNKNOWN"]
    else:
        assert result.outcome.value == "WORKFLOW_FAILED"
        assert persisted.status == "BLOCKED"
        assert models == provider.calls == []


def test_global_switch_and_workspace_activation_are_both_required(scope, monkeypatch):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    monkeypatch.setenv("NOVALTON_DURABLE_DISPATCH_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(ApplicationError) as error:
        tick(scope, provider)
    assert error.value.code == "dispatch_disabled"
    monkeypatch.setenv("NOVALTON_DURABLE_DISPATCH_ENABLED", "true")
    get_settings.cache_clear()
    db_call(
        lambda session: service.configure_workspace(
            session,
            operator=operator_for(scope),
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            enabled=False,
        )
    )
    with pytest.raises(ApplicationError) as error:
        claim(scope)
    assert error.value.code == "dispatch_disabled"
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "READY"
    assert attempts == models == provider.calls == []


def test_wrong_owner_and_old_activation_cannot_heartbeat_finalize_or_reserve(scope):
    from novalton_api.modules.durable_dispatch.authority import DispatchClaim

    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    old = claim(scope)
    wrong = replace(old, owner=uuid4())
    assert isinstance(wrong, DispatchClaim)
    assert not db_call(lambda session: repository.heartbeat(session, wrong))
    assert not db_call(lambda session: repository.finish(session, wrong))
    for enabled in (False, True):
        db_call(
            lambda session, enabled=enabled: service.configure_workspace(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                enabled=enabled,
            )
        )

    async def reserve(session):
        token = current_claim.set(old)
        try:
            await require_workflow(session, row.workflow_run_id)
        finally:
            current_claim.reset(token)

    with pytest.raises(ApplicationError) as error:
        db_call(reserve)
    assert error.value.code == "dispatch_disabled"
    assert not db_call(lambda session: repository.heartbeat(session, old))
    assert not db_call(lambda session: repository.finish(session, old))
    assert snapshot(scope, row.id)[1][0].outcome is None


def test_scoped_foreign_keys_and_dependency_scope_fail_closed(scope, monkeypatch):
    other = asyncio.run(_seed())
    provider = QueueProvider([])
    try:
        configure_operator(other, monkeypatch)
        db_call(
            lambda session: service.configure_workspace(
                session,
                operator=operator_for(other),
                tenant_id=other.tenant_id,
                workspace_id=other.workspace_id,
                enabled=False,
            )
        )
        foreign, _, _ = enqueue(other, provider)
        configure_operator(scope, monkeypatch)
        local, _, _ = enqueue(scope, provider)
        body, _ = _create_vertical(other_task(scope), provider)
        data = DispatchRequest(
            workflow_run_id=UUID(body["workflow_run"]["id"]),
            request_key=uuid4().hex,
            deadline=datetime.now(UTC) + timedelta(hours=1),
            dependencies=(foreign.id,),
        )
        with pytest.raises(ApplicationError) as error:
            db_call(
                lambda session: service.enqueue(
                    session,
                    operator=operator_for(scope),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    data=data,
                )
            )
        assert error.value.code == "dispatch_dependency_scope_mismatch"

        async def forge(session):
            await session.execute(
                update(TaskDispatch)
                .where(TaskDispatch.id == local.id)
                .values(workspace_id=other.workspace_id)
            )
            await session.commit()

        with pytest.raises(IntegrityError):
            db_call(forge)

        async def cleanup(session):
            await session.execute(delete(TaskDispatch).where(TaskDispatch.id == foreign.id))
            await session.execute(
                delete(DispatchActivation).where(DispatchActivation.tenant_id == other.tenant_id)
            )
            await session.commit()

        db_call(cleanup)
    finally:
        cleanup_operator(other)
        asyncio.run(_cleanup(other))
    assert provider.calls == []


def test_waiting_approval_releases_dispatch_for_an_independent_task(scope, tmp_path, monkeypatch):
    target = tmp_path / "fixture.txt"
    target.write_text("before\n")
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def policy(session):
        await policy_service.create_rule(
            session,
            data=PolicyRuleCreate(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                name="Durable exact approval",
                action_pattern="tool.workspace.replace_text",
                effect=PolicyEffect.REQUIRE_CONFIRMATION,
                actor_type="agent",
                resource_type="task",
            ),
        )

    db_call(policy)
    proposal = _worker() | {
        "status": "PARTIAL",
        "tool_proposals": [
            {
                "call_key": "durable_mutation",
                "tool_name": "workspace.replace_text",
                "arguments": {
                    "path": "fixture.txt",
                    "search": "before",
                    "replacement": "after",
                    "expected_matches": 1,
                },
            }
        ],
    }
    provider = QueueProvider([_manager(), proposal, _manager(), _worker(), _qa("PASS")])
    first, _, _ = enqueue(scope, provider, priority=10, max_model_calls=4)
    second, _, _ = enqueue(other_task(scope), provider, priority=0)
    assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
    assert tick(scope, provider).outcome.value == "WAITING_FOR_HUMAN"
    assert snapshot(scope, first.id)[0].status == "WAITING_HUMAN"
    assert target.read_text() == "before\n"
    assert tick(scope, provider).workflow_run_id == second.workflow_run_id
    assert snapshot(scope, first.id)[0].status == "WAITING_HUMAN"

    async def approval(session):
        value = await session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.tenant_id == scope.tenant_id)
        )
        assert value.status == "PENDING"
        return value.id

    identifier = db_call(approval)
    url = (
        f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}"
        f"/approvals/{identifier}/approve"
    )
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.post(url)
        assert response.status_code == 200, response.text
    assert target.read_text() == "after\n"
    assert tick(scope, provider).outcome.value == "WORKFLOW_COMPLETED"
    persisted, attempts, _ = snapshot(scope, first.id)
    assert (persisted.status, persisted.model_call_count, len(attempts)) == ("DONE", 4, 3)
    before = len(provider.calls)
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        assert client.post(url).status_code == 200
    assert len(provider.calls) == before == 5


def test_exhausted_model_budget_cannot_reserve_a_new_tool_effect(scope, tmp_path, monkeypatch):
    target = tmp_path / "fixture.txt"
    target.write_text("before\n")
    monkeypatch.setenv("NOVALTON_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()

    async def policy(session):
        await policy_service.create_rule(
            session,
            data=PolicyRuleCreate(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                name="Bounded read",
                action_pattern="tool.workspace.read_file",
                effect=PolicyEffect.ALLOW,
                actor_type="agent",
                resource_type="task",
            ),
        )

    db_call(policy)
    proposal = _worker() | {
        "status": "PARTIAL",
        "tool_proposals": [
            {
                "call_key": "budget_read",
                "tool_name": "workspace.read_file",
                "arguments": {"path": "fixture.txt"},
            }
        ],
    }
    provider = QueueProvider([_manager(), proposal])
    row, _, _ = enqueue(scope, provider, max_model_calls=2)
    assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
    assert tick(scope, provider).outcome.value == "WORKFLOW_FAILED"
    persisted, _, models = snapshot(scope, row.id)
    assert persisted.model_call_count == len(models) == len(provider.calls) == 2

    async def count(session):
        return await session.scalar(
            select(func.count()).select_from(ToolCall).where(ToolCall.tenant_id == scope.tenant_id)
        )

    assert db_call(count) == 0
    assert target.read_text() == "before\n"


def test_budget_counter_and_model_run_commit_atomically(scope, monkeypatch):
    from novalton_api.modules.model_usage import repository as usage_repository

    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)

    async def interrupted_insert(*args, **kwargs):
        raise RuntimeError("injected_model_insert_failure")

    monkeypatch.setattr(usage_repository, "create_run", interrupted_insert)
    with pytest.raises(RuntimeError, match="injected_model_insert_failure"):
        tick(scope, provider)
    persisted, attempts, models = snapshot(scope, row.id)
    assert (persisted.status, persisted.model_call_count) == ("BLOCKED", 0)
    assert attempts[0].reason_code == "dispatch_execution_interrupted"
    assert models == provider.calls == []


def test_managed_inflight_cancellation_finishes_queue_without_restarting_the_workflow(scope):
    provider = QueueProvider([_manager()])
    row, _, advance = enqueue(scope, provider)
    entered, released = threading.Event(), threading.Event()
    original = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await original(request)

    provider.complete = delayed
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(tick, scope, provider)
        assert entered.wait(15)
        try:
            with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
                url = advance.removesuffix("/advance") + "/cancel"
                assert client.post(url).status_code == 200
                assert client.post(url).status_code == 200
        finally:
            released.set()
        assert future.result(timeout=20).outcome.value == "CANCELLED"
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == attempts[0].outcome == "CANCELLED"
    assert models[0].status == "SUCCEEDED"
    assert len(provider.calls) == 1
    assert tick(scope, provider) is None
    assert len(provider.calls) == 1


def test_task_status_never_creates_or_authorizes_a_dispatch(scope):
    provider = QueueProvider([])

    async def mark_ready(session):
        await session.execute(update(Task).where(Task.id == scope.task_id).values(status="READY"))
        await session.commit()

    db_call(mark_ready)
    assert tick(scope, provider) is None
    assert provider.calls == []


def test_enqueue_refuses_to_adopt_an_already_started_manual_workflow(scope):
    provider = QueueProvider([_manager()])
    body, advance = _create_vertical(scope, provider)
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        assert client.post(advance).json()["outcome"] == "STEP_COMPLETED"
    data = DispatchRequest(
        workflow_run_id=UUID(body["workflow_run"]["id"]),
        request_key=uuid4().hex,
        deadline=datetime.now(UTC) + timedelta(hours=1),
    )
    with pytest.raises(ApplicationError) as error:
        db_call(
            lambda session: service.enqueue(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data=data,
            )
        )
    assert error.value.code == "dispatch_fresh_workflow_required"
    assert len(provider.calls) == 1


def test_manual_advance_cannot_overlap_an_unexpired_dispatch_claim(scope):
    provider = QueueProvider([])
    row, _, advance = enqueue(scope, provider)
    claimed = claim(scope)
    with TestClient(create_app(provider_registry=ProviderRegistry((provider,)))) as client:
        response = client.post(advance)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "dispatch_claim_required"
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.generation == claimed.generation == 1
    assert len(attempts) == 1
    assert models == provider.calls == []


def test_only_persisted_workflow_truth_can_mark_dispatch_done(scope):
    from novalton_api.modules.orchestrator.schemas import (
        OrchestrationOutcome,
        OrchestrationResult,
    )
    from novalton_api.modules.workflows.schemas import WorkflowRunStatus

    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    claimed = claim(scope)
    invented = OrchestrationResult(
        workflow_run_id=row.workflow_run_id,
        workflow_status=WorkflowRunStatus.COMPLETED,
        outcome=OrchestrationOutcome.WORKFLOW_COMPLETED,
        remaining_ready=0,
        remaining_pending=0,
    )
    assert db_call(lambda session: repository.finish(session, claimed, result=invented))
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "BLOCKED"
    assert persisted.stop_reason == "dispatch_result_state_mismatch"
    assert attempts[0].post_status == "CREATED"
    assert models == provider.calls == []


def test_qa_failure_is_blocked_and_never_reported_as_done(scope):
    provider = QueueProvider([_manager(), _worker(), _qa("FAIL")])
    row, _, _ = enqueue(scope, provider)
    for _ in range(2):
        assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
    assert tick(scope, provider).outcome.value == "WORKFLOW_FAILED"
    persisted, attempts, _ = snapshot(scope, row.id)
    assert persisted.status == "BLOCKED"
    assert attempts[-1].post_status == "FAILED"
    assert attempts[-1].outcome == "BLOCKED"
    assert tick(scope, provider) is None
    assert len(provider.calls) == 3


def test_old_generation_cannot_finalize_or_reserve_under_a_new_owner(scope):
    from novalton_api.modules.orchestrator import service as orchestrator

    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    old = claim(scope)

    async def complete_first(session):
        token = current_claim.set(old)
        try:
            result = await orchestrator.advance(
                session,
                registry=ProviderRegistry((provider,)),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                workflow_run_id=row.workflow_run_id,
            )
            assert await repository.finish(session, old, result=result)
        finally:
            current_claim.reset(token)

    db_call(complete_first)
    new = claim(scope)
    assert new.generation == old.generation + 1
    assert not db_call(lambda session: repository.heartbeat(session, old))
    assert not db_call(lambda session: repository.finish(session, old))

    async def stale_reservation(session):
        token = current_claim.set(old)
        try:
            await require_workflow(session, row.workflow_run_id)
        finally:
            current_claim.reset(token)

    with pytest.raises(ApplicationError) as error:
        db_call(stale_reservation)
    assert error.value.code == "dispatch_claim_lost"
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "LEASED"
    assert persisted.owner == new.owner
    assert len(attempts) == 2
    assert len(models) == len(provider.calls) == 1


def test_heartbeat_never_shortens_a_lease_and_cannot_extend_the_deadline(scope):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    claimed = claim(scope)
    before = snapshot(scope, row.id)[0]
    assert db_call(lambda session: repository.heartbeat(session, claimed, lease_seconds=60))
    after = snapshot(scope, row.id)[0]
    assert before.lease_expires_at <= after.lease_expires_at <= after.deadline
    assert after.generation == before.generation


def test_activation_changes_have_atomic_audit_evidence_and_rotate_generation(scope):
    from novalton_api.modules.audit.models import AuditRecord

    generations = []
    for enabled in (False, True):
        row = db_call(
            lambda session, enabled=enabled: service.configure_workspace(
                session,
                operator=operator_for(scope),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                enabled=enabled,
            )
        )
        generations.append(row.generation)
    assert generations == [2, 3]

    async def count(session):
        return await session.scalar(
            select(func.count())
            .select_from(AuditRecord)
            .where(
                AuditRecord.tenant_id == scope.tenant_id,
                AuditRecord.action == "dispatch.activation.configure",
            )
        )

    assert db_call(count) == 3


def test_one_claim_cannot_be_reused_to_advance_a_second_step(scope):
    from novalton_api.modules.orchestrator import service as orchestrator

    provider = QueueProvider([_manager()])
    row, _, _ = enqueue(scope, provider)
    claimed = claim(scope)

    async def execute(session):
        token = current_claim.set(claimed)
        try:
            first = await orchestrator.advance(
                session,
                registry=ProviderRegistry((provider,)),
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                workflow_run_id=row.workflow_run_id,
            )
            assert first.outcome.value == "STEP_COMPLETED"
            with pytest.raises(ApplicationError) as error:
                await orchestrator.advance(
                    session,
                    registry=ProviderRegistry((provider,)),
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    workflow_run_id=row.workflow_run_id,
                )
            assert error.value.code == "dispatch_step_claim_conflict"
            await session.rollback()
            assert await repository.finish(session, claimed, result=first)
        finally:
            current_claim.reset(token)

    db_call(execute)
    persisted, attempts, models = snapshot(scope, row.id)
    state = asyncio.run(_vertical_state(scope, row.workflow_run_id))
    assert persisted.status == "READY"
    assert attempts[0].workflow_step_run_id == state["rows"][0][0].id
    assert state["rows"][1][0].status == "READY"
    assert len(models) == len(provider.calls) == 1


def test_attempt_step_evidence_cannot_reference_another_workflow_even_in_the_same_workspace(scope):
    from novalton_api.modules.workflows.models import WorkflowStepRun

    provider = QueueProvider([])
    first, _, _ = enqueue(scope, provider, priority=10)
    second, _, _ = enqueue(other_task(scope), provider, priority=0)
    claimed = claim(scope)
    assert claimed.dispatch_id == first.id

    async def forge(session):
        foreign_step = await session.scalar(
            select(WorkflowStepRun.id)
            .where(WorkflowStepRun.workflow_run_id == second.workflow_run_id)
            .limit(1)
        )
        await session.execute(
            update(DispatchAttempt)
            .where(
                DispatchAttempt.dispatch_id == first.id,
                DispatchAttempt.generation == claimed.generation,
            )
            .values(workflow_step_run_id=foreign_step)
        )
        await session.commit()

    with pytest.raises(IntegrityError):
        db_call(forge)
    assert snapshot(scope, first.id)[1][0].workflow_step_run_id is None
    assert provider.calls == []


def test_heartbeat_lock_wait_cannot_resurrect_a_lease_that_expired_while_waiting(scope):
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    claimed = claim(scope)
    entered, release = threading.Event(), threading.Event()

    def hold_row():
        async def hold(session):
            await session.scalar(
                select(TaskDispatch).where(TaskDispatch.id == row.id).with_for_update()
            )
            entered.set()
            assert await asyncio.to_thread(release.wait, 15)
            # This expiry is later than a waiting heartbeat's old timestamp,
            # but already elapsed when that heartbeat finally acquires the row.
            await session.execute(
                update(TaskDispatch)
                .where(TaskDispatch.id == row.id)
                .values(lease_expires_at=func.clock_timestamp())
            )
            await session.commit()

        db_call(hold)

    async def heartbeat_waiting(session):
        for _ in range(100):
            waiting = await session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND query LIKE '%task_dispatches%')"
                )
            )
            if waiting:
                return True
            await session.rollback()
            await asyncio.sleep(0.05)
        return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        holder = executor.submit(hold_row)
        assert entered.wait(15)
        renewing = executor.submit(db_call, lambda session: repository.heartbeat(session, claimed))
        try:
            assert db_call(heartbeat_waiting)
        finally:
            release.set()
        holder.result(timeout=15)
        assert renewing.result(timeout=15) is False
    assert tick(scope, provider) is None
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.stop_reason == "dispatch_lease_expired"
    assert len(attempts) == 1
    assert models == provider.calls == []


def test_claim_context_cannot_authorize_tools_for_an_unlinked_agent(scope, tmp_path):
    from novalton_api.modules.agents import service as agents_service
    from novalton_api.modules.agents.models import AgentDefinition
    from novalton_api.modules.agents.schemas import AgentRunCreate
    from novalton_api.modules.tools import service as tools_service
    from novalton_api.modules.tools.contracts import ToolProposal
    from novalton_api.modules.tools.executor import WorkspaceRoot

    (tmp_path / "fixture.txt").write_text("bounded\n")
    provider = QueueProvider([])
    row, _, _ = enqueue(scope, provider)
    claimed = claim(scope)

    async def reserve(session):
        definition_id = await session.scalar(
            select(AgentDefinition.id).where(
                AgentDefinition.tenant_id == scope.tenant_id,
                AgentDefinition.workspace_id == scope.workspace_id,
                AgentDefinition.slug == "developer_worker",
            )
        )
        agent = await agents_service.create_run(
            session,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            data=AgentRunCreate(
                agent_definition_id=definition_id,
                project_id=scope.project_id,
                task_id=scope.task_id,
            ),
        )
        agent = await agents_service.start_run(
            session,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            run_id=agent.id,
        )
        await policy_service.create_rule(
            session,
            data=PolicyRuleCreate(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                name="Standalone bounded read",
                action_pattern="tool.workspace.read_file",
                effect=PolicyEffect.ALLOW,
                actor_type="agent",
                resource_type="task",
            ),
        )
        token = current_claim.set(claimed)
        try:
            await tools_service.execute_proposal(
                session,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                agent_run_id=agent.id,
                proposal=ToolProposal.model_validate(
                    {
                        "call_key": "unlinked_read",
                        "tool_name": "workspace.read_file",
                        "arguments": {"path": "fixture.txt"},
                    }
                ),
                permitted_tools=["workspace.read_file"],
                workspace_root=WorkspaceRoot.approved(tmp_path),
            )
        finally:
            current_claim.reset(token)

    with pytest.raises(ApplicationError) as error:
        db_call(reserve)
    assert error.value.code == "dispatch_scope_mismatch"

    async def count(session):
        return await session.scalar(
            select(func.count()).select_from(ToolCall).where(ToolCall.tenant_id == scope.tenant_id)
        )

    assert db_call(count) == 0
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "LEASED"
    assert len(attempts) == 1
    assert models == provider.calls == []
