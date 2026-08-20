"""Bounded, database-backed Server-Sent Events delivery."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from time import monotonic
from uuid import UUID

from novalton_api.core.database import Database
from novalton_api.modules.runtime_events import service
from novalton_api.modules.runtime_events.models import RuntimeEvent

STREAM_BATCH_SIZE = 50
POLL_INTERVAL_SECONDS = 1.0
HEARTBEAT_INTERVAL_SECONDS = 15.0
HEARTBEAT_FRAME = ": heartbeat\n\n"


def event_frame(event: RuntimeEvent) -> str:
    data: dict[str, object] = {
        "id": str(event.id),
        "event_type": event.event_type,
        "source": event.source,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload,
    }
    if event.correlation_id is not None:
        data["correlation_id"] = event.correlation_id
    if event.project_id is not None:
        data["project_id"] = str(event.project_id)
    if event.task_id is not None:
        data["task_id"] = str(event.task_id)
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"id: {event.id}\nevent: {event.event_type}\ndata: {encoded}\n\n"


async def stream_events(
    database: Database,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    cursor: RuntimeEvent | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    poll_interval: float = POLL_INTERVAL_SECONDS,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
    clock: Callable[[], float] = monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    """Yield scoped frames while releasing the database session after every poll."""
    last_heartbeat = clock()
    current = cursor
    while not await is_disconnected():
        async with database.session_factory() as session:
            batch = await service.list_stream_batch(
                session,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                cursor=current,
                limit=STREAM_BATCH_SIZE,
            )
        if batch:
            for event in batch:
                if await is_disconnected():
                    return
                yield event_frame(event)
                current = event
            continue
        now = clock()
        if now - last_heartbeat >= heartbeat_interval:
            yield HEARTBEAT_FRAME
            last_heartbeat = now
        await sleep(poll_interval)
