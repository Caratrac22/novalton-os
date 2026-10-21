"""Bounded end-to-end dispatch workload using the actual three-agent workflow."""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from statistics import median
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_development_workflow import _manager, _qa, _worker
from test_durable_dispatch import db_call, enqueue, operator_for, other_task, snapshot, tick

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.core.exceptions import ApplicationError
from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.durable_dispatch import provisioning, service
from novalton_api.modules.durable_dispatch.models import DispatchAttempt, TaskDispatch
from novalton_api.modules.model_usage.models import ModelRun

pytest_plugins = ["test_durable_dispatch"]


class RoleProvider:
    """Return the role's valid contract without depending on worker arrival order."""

    provider_id = "mock"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.lock = threading.Lock()

    async def complete(self, request: GenerationRequest) -> GenerationResult:
        system = request.messages[0].content
        if "Novalton Agent 'Developer Manager'" in system:
            role, result = "manager", _manager()
        elif "Novalton Agent 'Developer Worker'" in system:
            role, result = "developer", _worker()
        elif "Novalton Agent 'QA Worker'" in system:
            role, result = "qa", _qa("PASS")
        else:
            raise AssertionError("unknown governed role")
        with self.lock:
            self.calls.append(role)
        return GenerationResult(
            provider_id=self.provider_id,
            model_id=request.model_id,
            content=json.dumps(result),
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            duration_ms=1,
        )


@pytest.mark.parametrize("step_index", [0, 1, 2])
def test_membership_revocation_during_each_role_preserves_late_model_evidence(scope, step_index):
    provider = RoleProvider()
    row, _, _ = enqueue(scope, provider, max_attempts=3, max_model_calls=3)
    for _ in range(step_index):
        assert tick(scope, provider).outcome.value == "STEP_COMPLETED"
    entered, released = threading.Event(), threading.Event()
    complete = provider.complete

    async def delayed(request):
        entered.set()
        assert await asyncio.to_thread(released.wait, 15)
        return await complete(request)

    provider.complete = delayed
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(tick, scope, provider)
        assert entered.wait(15)
        try:
            actor = operator_for(scope)
            assert db_call(
                lambda session: provisioning.revoke_tenant_membership(
                    session,
                    operator=actor,
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    subject_id=actor.user_id,
                )
            )
        finally:
            released.set()
        with pytest.raises(ApplicationError) as interrupted:
            active.result(timeout=20)
        assert interrupted.value.status_code == 403
    dispatch, attempts, models = snapshot(scope, row.id)
    assert dispatch.status == "BLOCKED"
    assert (
        dispatch.attempt_count
        == len(attempts)
        == len(models)
        == len(provider.calls)
        == step_index + 1
    )
    assert all(model.status == "SUCCEEDED" for model in models)
    assert provider.calls == ["manager", "developer", "qa"][: step_index + 1]
    with pytest.raises(ApplicationError):
        tick(scope, provider)


@pytest.mark.parametrize("count", [10, 25, 50])
def test_complete_workflows_with_six_workers(scope, capsys, count):
    provider = RoleProvider()
    rows = []
    for index in range(count):
        task_scope = scope if index == 0 else other_task(scope)
        row, _, _ = enqueue(
            task_scope,
            provider,
            priority=index % 3 - 1,
            max_attempts=3,
            max_model_calls=3,
        )
        rows.append(row)
    registry = ProviderRegistry((provider,))
    completed: set = set()
    errors: list[str] = []
    lock = threading.Lock()
    abort = threading.Event()

    def worker():
        async def execute():
            database = Database.from_settings(Settings.from_environment())
            try:
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    if abort.is_set():
                        return
                    with lock:
                        if len(completed) == count:
                            return
                    async with database.session_factory() as session:
                        result = await service.run_once(
                            session,
                            registry=registry,
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            owner=uuid4(),
                        )
                    if result is None:
                        await asyncio.sleep(0.01)
                    elif result.outcome.value == "WORKFLOW_COMPLETED":
                        with lock:
                            completed.add(result.workflow_run_id)
                raise TimeoutError("bounded complete-workflow workload did not finish")
            finally:
                await database.dispose()

        try:
            asyncio.run(execute())
        except Exception as exc:
            with lock:
                errors.append(exc.code if isinstance(exc, ApplicationError) else type(exc).__name__)
            abort.set()

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=6) as executor:
        for future in [executor.submit(worker) for _ in range(6)]:
            future.result(timeout=260)
    elapsed = time.perf_counter() - started
    assert errors == []
    assert len(completed) == count

    async def evidence(session):
        attempts = list(
            await session.execute(
                select(
                    TaskDispatch.id,
                    TaskDispatch.status,
                    TaskDispatch.created_at,
                    func.max(DispatchAttempt.completed_at),
                    func.count(DispatchAttempt.id),
                )
                .join(DispatchAttempt, DispatchAttempt.dispatch_id == TaskDispatch.id)
                .where(TaskDispatch.id.in_([row.id for row in rows]))
                .group_by(TaskDispatch.id)
            )
        )
        models = await session.scalar(
            select(func.count()).select_from(ModelRun).where(ModelRun.tenant_id == scope.tenant_id)
        )
        return attempts, models

    attempts, models = db_call(evidence)
    assert len(attempts) == count
    assert all(status == "DONE" and generations == 3 for _, status, _, _, generations in attempts)
    assert models == len(provider.calls) == count * 3
    assert provider.calls.count("manager") == provider.calls.count("developer") == count
    assert provider.calls.count("qa") == count
    latencies = sorted(
        (finished - created).total_seconds() for _, _, created, finished, _ in attempts
    )

    def percentile(frac):
        return round(latencies[min(len(latencies) - 1, int((len(latencies) - 1) * frac))], 3)

    measurement = {
        "complete_workflows": count,
        "workers": 6,
        "elapsed_seconds": round(elapsed, 3),
        "completed_per_second": round(count / elapsed, 2),
        "end_to_end_p50_seconds": round(median(latencies), 3),
        "end_to_end_p95_seconds": percentile(0.95),
        "end_to_end_p99_seconds": percentile(0.99),
        "model_runs": models,
        "errors": len(errors),
    }
    with capsys.disabled():
        print("dispatch_complete " + json.dumps(measurement, sort_keys=True), flush=True)


def test_progressive_complete_workflows_with_mixed_generation_latency(scope, capsys):
    """Bounded arrival stream; measure completed workflows, including queue time."""
    provider = RoleProvider()
    complete = provider.complete

    async def delayed(request):
        # Deterministic short and long local generations, never a paid provider.
        await asyncio.sleep(0.003 if len(provider.calls) % 3 else 0.025)
        return await complete(request)

    provider.complete = delayed
    registry = ProviderRegistry((provider,))
    count = 12
    rows = []
    completed = set()
    errors = []
    lock = threading.Lock()
    feeding = threading.Event()
    feeding.set()

    def worker():
        async def execute():
            database = Database.from_settings(Settings.from_environment())
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    with lock:
                        if not feeding.is_set() and len(completed) == count:
                            return
                    async with database.session_factory() as session:
                        result = await service.run_once(
                            session,
                            registry=registry,
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            owner=uuid4(),
                        )
                    if result is None:
                        await asyncio.sleep(0.01)
                    elif result.outcome.value == "WORKFLOW_COMPLETED":
                        with lock:
                            completed.add(result.workflow_run_id)
                raise TimeoutError("progressive workflow stream did not finish")
            finally:
                await database.dispose()

        try:
            asyncio.run(execute())
        except Exception as exc:
            with lock:
                errors.append(exc.code if isinstance(exc, ApplicationError) else type(exc).__name__)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker) for _ in range(4)]
        for index in range(count):
            task_scope = scope if index == 0 else other_task(scope)
            row, _, _ = enqueue(
                task_scope,
                provider,
                priority=index % 3 - 1,
                max_attempts=3,
                max_model_calls=3,
            )
            rows.append(row)
            time.sleep(0.03)
        feeding.clear()
        for future in futures:
            future.result(timeout=125)
    elapsed = time.perf_counter() - started
    assert errors == []
    assert len(completed) == count

    async def evidence(session):
        return list(
            await session.execute(
                select(
                    TaskDispatch.id,
                    TaskDispatch.status,
                    TaskDispatch.created_at,
                    func.max(DispatchAttempt.completed_at),
                    func.count(DispatchAttempt.id),
                )
                .join(DispatchAttempt, DispatchAttempt.dispatch_id == TaskDispatch.id)
                .where(TaskDispatch.id.in_([row.id for row in rows]))
                .group_by(TaskDispatch.id)
            )
        )

    records = db_call(evidence)
    assert len(records) == count
    assert all(status == "DONE" and attempts == 3 for _, status, _, _, attempts in records)
    assert len(provider.calls) == count * 3
    latencies = sorted(
        (finished - created).total_seconds() for _, _, created, finished, _ in records
    )

    def percentile(frac):
        return round(latencies[min(count - 1, int((count - 1) * frac))], 3)

    with capsys.disabled():
        print(
            "dispatch_progressive "
            + json.dumps(
                {
                    "complete_workflows": count,
                    "workers": 4,
                    "elapsed_seconds": round(elapsed, 3),
                    "completed_per_second": round(count / elapsed, 2),
                    "end_to_end_p50_seconds": round(median(latencies), 3),
                    "end_to_end_p95_seconds": percentile(0.95),
                    "end_to_end_p99_seconds": percentile(0.99),
                    "model_runs": len(provider.calls),
                    "errors": len(errors),
                    "arrival_interval_seconds": 0.03,
                },
                sort_keys=True,
            ),
            flush=True,
        )


def test_completed_workflows_after_bounded_worker_restart(scope, capsys):
    """Worker turnover at committed step boundaries cannot replay Manager or QA."""
    provider = RoleProvider()
    complete = provider.complete

    async def delayed(request):
        await asyncio.sleep(0.005 if len(provider.calls) % 2 else 0.02)
        return await complete(request)

    provider.complete = delayed
    registry = ProviderRegistry((provider,))
    count = 10
    rows = []
    for index in range(count):
        task_scope = scope if index == 0 else other_task(scope)
        row, _, _ = enqueue(
            task_scope,
            provider,
            priority=index % 3 - 1,
            max_attempts=3,
            max_model_calls=3,
        )
        rows.append(row)

    def worker(max_ticks):
        async def execute():
            database = Database.from_settings(Settings.from_environment())
            try:
                deadline = time.monotonic() + 120
                ticks = 0
                while time.monotonic() < deadline and ticks < max_ticks:
                    async with database.session_factory() as session:
                        result = await service.run_once(
                            session,
                            registry=registry,
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            owner=uuid4(),
                        )
                    if result is None:
                        await asyncio.sleep(0.01)
                    else:
                        ticks += 1
                if ticks < max_ticks:
                    raise TimeoutError("bounded restart workload did not finish")
            finally:
                await database.dispose()

        asyncio.run(execute())

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        for future in [executor.submit(worker, 3) for _ in range(2)]:
            future.result(timeout=130)
    first_phase = len(provider.calls)
    assert first_phase == 6

    def finish_worker():
        async def execute():
            database = Database.from_settings(Settings.from_environment())
            try:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    async with database.session_factory() as session:
                        done = await session.scalar(
                            select(func.count())
                            .select_from(TaskDispatch)
                            .where(
                                TaskDispatch.id.in_([row.id for row in rows]),
                                TaskDispatch.status == "DONE",
                            )
                        )
                        if done == count:
                            return
                        result = await service.run_once(
                            session,
                            registry=registry,
                            tenant_id=scope.tenant_id,
                            workspace_id=scope.workspace_id,
                            owner=uuid4(),
                        )
                    if result is None:
                        await asyncio.sleep(0.01)
                raise TimeoutError("restart completion did not finish")
            finally:
                await database.dispose()

        asyncio.run(execute())

    with ThreadPoolExecutor(max_workers=4) as executor:
        for future in [executor.submit(finish_worker) for _ in range(4)]:
            future.result(timeout=130)
    elapsed = time.perf_counter() - started

    async def evidence(session):
        return list(
            await session.execute(
                select(
                    TaskDispatch.status,
                    TaskDispatch.created_at,
                    func.max(DispatchAttempt.completed_at),
                    func.count(DispatchAttempt.id),
                )
                .join(DispatchAttempt, DispatchAttempt.dispatch_id == TaskDispatch.id)
                .where(TaskDispatch.id.in_([row.id for row in rows]))
                .group_by(TaskDispatch.id)
            )
        )

    records = db_call(evidence)
    assert len(records) == count
    assert all(status == "DONE" and attempts == 3 for status, _, _, attempts in records)
    assert len(provider.calls) == count * 3
    assert provider.calls.count("manager") == count
    assert provider.calls.count("developer") == count
    assert provider.calls.count("qa") == count
    latencies = sorted((finished - created).total_seconds() for _, created, finished, _ in records)
    with capsys.disabled():
        print(
            "dispatch_restart "
            + json.dumps(
                {
                    "complete_workflows": count,
                    "workers_before": 2,
                    "workers_after": 4,
                    "elapsed_seconds": round(elapsed, 3),
                    "completed_per_second": round(count / elapsed, 2),
                    "end_to_end_p50_seconds": round(median(latencies), 3),
                    "end_to_end_p95_seconds": round(latencies[int((count - 1) * 0.95)], 3),
                    "end_to_end_p99_seconds": round(latencies[int((count - 1) * 0.99)], 3),
                    "model_runs": len(provider.calls),
                    "first_phase_model_runs": first_phase,
                },
                sort_keys=True,
            ),
            flush=True,
        )
