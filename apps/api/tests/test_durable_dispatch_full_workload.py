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
from test_durable_dispatch import db_call, enqueue, other_task

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.infrastructure.providers.contracts import GenerationRequest, GenerationResult
from novalton_api.infrastructure.providers.registry import ProviderRegistry
from novalton_api.modules.durable_dispatch import service
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

    def worker():
        async def execute():
            database = Database.from_settings(Settings.from_environment())
            try:
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
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
                errors.append(type(exc).__name__)

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
