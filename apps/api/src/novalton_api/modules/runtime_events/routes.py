"""Tenant/workspace-scoped RuntimeEvent streaming route."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from novalton_api.core.database import get_database
from novalton_api.modules.runtime_events import service
from novalton_api.modules.runtime_events.stream import stream_events

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/events",
    tags=["runtime-events"],
)


@router.get("/stream")
async def runtime_event_stream(
    tenant_id: UUID,
    workspace_id: UUID,
    request: Request,
    last_event_id: Annotated[UUID | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    database = get_database(request)
    async with database.session_factory() as session:
        cursor = await service.validate_stream_scope(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            cursor_id=last_event_id,
        )
    return StreamingResponse(
        stream_events(
            database,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            cursor=cursor,
            is_disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
