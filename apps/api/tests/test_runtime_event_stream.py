import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from novalton_api.core.config import Settings
from novalton_api.core.database import Database
from novalton_api.main import create_app
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.projects.models import Project
from novalton_api.modules.runtime_events import service
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.runtime_events.routes import runtime_event_stream
from novalton_api.modules.runtime_events.schemas import RuntimeEventCreate
from novalton_api.modules.runtime_events.stream import HEARTBEAT_FRAME, event_frame, stream_events
from novalton_api.modules.tasks.models import Task
from novalton_api.modules.tenants.models import Tenant
from novalton_api.modules.workspaces.models import Workspace


@dataclass(frozen=True)
class Scope:
    tenant_id: UUID
    workspace_id: UUID


async def _reset_and_seed() -> tuple[Scope, Scope]:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(AuditRecord))
            await session.execute(delete(RuntimeEvent))
            await session.execute(delete(Task))
            await session.execute(delete(Project))
            await session.execute(delete(Workspace))
            await session.execute(delete(Tenant))
            tenants = [
                Tenant(name=f"Tenant {index}", slug=f"stream-{index}-{uuid4().hex[:6]}")
                for index in (1, 2)
            ]
            session.add_all(tenants)
            await session.flush()
            workspaces = [
                Workspace(tenant_id=tenant.id, name="Stream", slug="stream") for tenant in tenants
            ]
            session.add_all(workspaces)
            await session.flush()
            return tuple(
                Scope(tenant.id, workspace.id)
                for tenant, workspace in zip(tenants, workspaces, strict=True)
            )  # type: ignore[return-value]
    finally:
        await database.dispose()


async def _reset() -> None:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory.begin() as session:
            await session.execute(delete(AuditRecord))
            await session.execute(delete(RuntimeEvent))
            await session.execute(delete(Task))
            await session.execute(delete(Project))
            await session.execute(delete(Workspace))
            await session.execute(delete(Tenant))
    finally:
        await database.dispose()


@pytest.fixture
def scopes() -> Iterator[tuple[Scope, Scope]]:
    value = asyncio.run(_reset_and_seed())
    yield value
    asyncio.run(_reset())


def _url(scope: Scope) -> str:
    return f"/api/v1/tenants/{scope.tenant_id}/workspaces/{scope.workspace_id}/events/stream"


async def _append(scope: Scope, *, event_type: str, occurred_at: datetime) -> RuntimeEvent:
    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            return await service.append_event(
                session,
                data=RuntimeEventCreate(
                    tenant_id=scope.tenant_id,
                    workspace_id=scope.workspace_id,
                    event_type=event_type,
                    source="stream_test",
                    correlation_id="req-stream",
                    payload={"state": event_type},
                ),
                occurred_at=occurred_at,
            )
    finally:
        await database.dispose()


async def _finite_stream(*_: object, **__: object) -> AsyncIterator[str]:
    yield ": heartbeat\n\n"


@pytest.mark.asyncio
async def test_endpoint_validates_scope_and_returns_sse_headers(
    scopes: tuple[Scope, Scope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _ = scopes
    monkeypatch.setattr("novalton_api.modules.runtime_events.routes.stream_events", _finite_stream)
    monkeypatch.setattr(
        "novalton_api.modules.runtime_events.routes.service.validate_stream_scope",
        AsyncMock(return_value=None),
    )

    class SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    database = SimpleNamespace(session_factory=SessionContext)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(database=database)),
        is_disconnected=lambda: None,
    )
    response = await runtime_event_stream(
        first.tenant_id, first.workspace_id, request, last_event_id=None
    )
    body = "".join([chunk async for chunk in response.body_iterator])
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert body == HEARTBEAT_FRAME


def test_endpoint_rejects_unknown_workspace(scopes: tuple[Scope, Scope]) -> None:
    first, _ = scopes
    with TestClient(create_app()) as client:
        unknown = client.get(_url(Scope(first.tenant_id, uuid4())))
        assert unknown.status_code == 404
        assert unknown.json()["error"] == {
            "code": "resource_not_found",
            "message": "Resource not found",
        }


def test_malformed_and_foreign_cursor_are_sanitized_and_private(
    scopes: tuple[Scope, Scope], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = scopes
    foreign = asyncio.run(_append(second, event_type="task.created", occurred_at=datetime.now(UTC)))
    monkeypatch.setattr("novalton_api.modules.runtime_events.routes.stream_events", _finite_stream)
    with TestClient(create_app()) as client:
        malformed = client.get(_url(first), headers={"Last-Event-ID": "not-a-uuid"})
        assert malformed.status_code == 422
        assert malformed.json()["error"]["message"] == "Request validation failed"
        assert "not-a-uuid" not in malformed.text

        foreign_response = client.get(_url(first), headers={"Last-Event-ID": str(foreign.id)})
        unknown_response = client.get(_url(first), headers={"Last-Event-ID": str(uuid4())})
        assert foreign_response.status_code == unknown_response.status_code == 404
        assert foreign_response.json()["error"] == unknown_response.json()["error"]


@pytest.mark.asyncio
async def test_order_resume_isolation_and_safe_deterministic_framing(
    scopes: tuple[Scope, Scope],
) -> None:
    first, second = scopes
    now = datetime.now(UTC)
    oldest = await _append(first, event_type="task.created", occurred_at=now - timedelta(seconds=2))
    cursor = await _append(first, event_type="task.started", occurred_at=now - timedelta(seconds=1))
    newest = await _append(first, event_type="task.completed", occurred_at=now)
    await _append(second, event_type="task.private", occurred_at=now + timedelta(seconds=1))

    database = Database.from_settings(Settings())
    try:
        async with database.session_factory() as session:
            initial = await service.list_stream_batch(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                cursor=None,
                limit=50,
            )
            resumed = await service.list_stream_batch(
                session,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                cursor=cursor,
                limit=50,
            )
        assert [event.id for event in initial] == [oldest.id, cursor.id, newest.id]
        assert [event.id for event in resumed] == [newest.id]
        frame = event_frame(newest)
        assert frame.startswith(f"id: {newest.id}\nevent: task.completed\ndata: ")
        assert frame.endswith("\n\n")
        data = json.loads(frame.split("data: ", 1)[1])
        assert data == {
            "correlation_id": "req-stream",
            "event_type": "task.completed",
            "id": str(newest.id),
            "occurred_at": newest.occurred_at.isoformat(),
            "payload": {"state": "task.completed"},
            "source": "stream_test",
        }
        assert "audit" not in frame.casefold()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_heartbeat_and_disconnect_are_deterministic_and_close_sessions(
    scopes: tuple[Scope, Scope],
) -> None:
    first, _ = scopes
    database = Database.from_settings(Settings())
    times = iter((0.0, 2.0))
    disconnected = False

    async def is_disconnected() -> bool:
        return disconnected

    async def stop(_: float) -> None:
        nonlocal disconnected
        disconnected = True

    try:
        frames = [
            frame
            async for frame in stream_events(
                database,
                tenant_id=first.tenant_id,
                workspace_id=first.workspace_id,
                cursor=None,
                is_disconnected=is_disconnected,
                poll_interval=1.0,
                heartbeat_interval=1.0,
                clock=lambda: next(times),
                sleep=stop,
            )
        ]
        assert frames == [HEARTBEAT_FRAME]
        assert database.engine.pool.checkedout() == 0
    finally:
        await database.dispose()
