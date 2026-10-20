"""Disposable PostgreSQL acceptance for the bounded trusted dispatcher."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
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
from novalton_api.modules.durable_dispatch import repository, service
from novalton_api.modules.durable_dispatch.authority import (
    current_claim,
    require_workflow,
)
from novalton_api.modules.durable_dispatch.models import (
    DispatchActivation,
    DispatchAttempt,
    DispatchDependency,
    TaskDispatch,
)
from novalton_api.modules.durable_dispatch.schemas import DispatchRequest
from novalton_api.modules.model_catalog.models import ModelDefinition
from novalton_api.modules.model_usage.models import ModelRun
from novalton_api.modules.policy import service as policy_service
from novalton_api.modules.policy.schemas import PolicyEffect, PolicyRuleCreate
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tools.models import ToolCall


def db_call(operation):
    async def execute():
        database = Database.from_settings(Settings.from_environment())
        try:
            async with database.session_factory() as session:
                return await operation(session)
        finally:
            await database.dispose()

    return asyncio.run(execute())


@pytest.fixture
def scope(monkeypatch):
    monkeypatch.setenv("NOVALTON_DURABLE_DISPATCH_ENABLED", "true")
    get_settings.cache_clear()
    value = asyncio.run(_seed())
    db_call(
        lambda session: service.configure_workspace(
            session, tenant_id=value.tenant_id, workspace_id=value.workspace_id, enabled=True
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
            session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, data=data
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


def test_enqueue_idempotency_is_atomic_and_conflicting_bindings_fail(scope):
    provider = QueueProvider([])
    row, data, _ = enqueue(scope, provider)

    def repeat():
        return db_call(
            lambda session: service.enqueue(
                session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, data=data
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
    assert len(models) == 1 and models[0].status == "RUNNING"
    assert current_claim.get() is None
    expire(row.id)
    assert tick(scope, provider) is None
    persisted, attempts, models = snapshot(scope, row.id)
    assert persisted.status == "BLOCKED"
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
            session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, enabled=False
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


def test_scoped_foreign_keys_and_dependency_scope_fail_closed(scope):
    other = asyncio.run(_seed())
    provider = QueueProvider([])
    try:
        db_call(
            lambda session: service.configure_workspace(
                session, tenant_id=other.tenant_id, workspace_id=other.workspace_id, enabled=False
            )
        )
        foreign, _, _ = enqueue(other, provider)
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
                    session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, data=data
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
                session, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id, data=data
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
