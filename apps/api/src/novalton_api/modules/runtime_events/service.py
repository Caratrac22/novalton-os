"""Runtime event validation, scoping, and transaction boundaries."""

import json
import logging
import math
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.projects import repository as projects_repository
from novalton_api.modules.runtime_events import repository
from novalton_api.modules.runtime_events.models import RuntimeEvent
from novalton_api.modules.runtime_events.schemas import MAX_PAYLOAD_BYTES, RuntimeEventCreate
from novalton_api.modules.tasks import repository as tasks_repository
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)
_MAX_PAYLOAD_DEPTH = 8
_MAX_PAYLOAD_ITEMS = 256
_MAX_STRING_LENGTH = 2048
_FORBIDDEN_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "authorizationheader",
    "bearertoken",
    "clientsecret",
    "cookie",
    "credential",
    "idtoken",
    "password",
    "passwd",
    "refreshtoken",
    "secret",
    "setcookie",
    "token",
}


def _invalid_event(message: str) -> ApplicationError:
    return ApplicationError("invalid_runtime_event", message, status_code=422)


def _not_found() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


def _normalized_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _forbidden_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return any(marker in normalized for marker in _FORBIDDEN_KEYS)


def _credential_bearing_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username is not None or parsed.password is not None:
        return True
    return any(_forbidden_key(key) for key, _ in parse_qsl(parsed.query))


def _validate_json_value(value: Any, *, depth: int, item_count: list[int]) -> None:
    if depth > _MAX_PAYLOAD_DEPTH:
        raise _invalid_event("Runtime event payload is too deeply nested")
    item_count[0] += 1
    if item_count[0] > _MAX_PAYLOAD_ITEMS:
        raise _invalid_event("Runtime event payload contains too many values")

    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid_event("Runtime event payload contains a non-finite number")
        return
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            raise _invalid_event("Runtime event payload contains an oversized string")
        if _credential_bearing_url(value):
            raise _invalid_event("Runtime event payload contains a credential-bearing URL")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1, item_count=item_count)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid_event("Runtime event payload keys must be strings")
            if _forbidden_key(key):
                raise _invalid_event("Runtime event payload contains a forbidden field")
            _validate_json_value(item, depth=depth + 1, item_count=item_count)
        return
    raise _invalid_event("Runtime event payload contains a non-JSON value")


def safe_payload(payload: dict[str, Any] | None) -> dict[str, object] | None:
    """Validate and normalize a small secret-free JSON object."""
    if payload is None:
        return None
    _validate_json_value(payload, depth=0, item_count=[0])
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _invalid_event("Runtime event payload is not JSON serializable") from None
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise _invalid_event("Runtime event payload exceeds 8192 bytes")
    return json.loads(encoded)


async def _validate_scope(session: AsyncSession, data: RuntimeEventCreate) -> None:
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=data.tenant_id, workspace_id=data.workspace_id
    )
    if workspace is None:
        raise _not_found()
    if data.task_id is not None and data.project_id is None:
        raise _invalid_event("task_id requires project_id")
    if data.project_id is not None:
        project = await projects_repository.get_project(
            session, workspace_id=data.workspace_id, project_id=data.project_id
        )
        if project is None:
            raise _not_found()
    if data.task_id is not None:
        task = await tasks_repository.get_task(
            session, project_id=data.project_id, task_id=data.task_id
        )
        if task is None:
            raise _not_found()


async def append_event(
    session: AsyncSession,
    *,
    data: RuntimeEventCreate,
    occurred_at: datetime | None = None,
    commit: bool = True,
) -> RuntimeEvent:
    """Append one event, optionally joining an existing business transaction."""
    try:
        payload = safe_payload(data.payload)
        await _validate_scope(session, data)
        event = await repository.append_event(
            session,
            tenant_id=data.tenant_id,
            workspace_id=data.workspace_id,
            event_type=data.event_type,
            source=data.source,
            occurred_at=occurred_at,
            correlation_id=data.correlation_id or get_correlation_id(),
            project_id=data.project_id,
            task_id=data.task_id,
            payload=payload,
        )
        if commit:
            await session.commit()
            await session.refresh(event)
    except ApplicationError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Runtime event persistence failed",
            extra={
                "event": "runtime_event.persistence_failed",
                "exception_type": type(exc).__name__,
            },
        )
        raise ApplicationError(
            "runtime_event_persistence_failed",
            "Runtime event could not be persisted",
            status_code=500,
        ) from None
    return event


async def list_recent_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int = 50,
) -> list[RuntimeEvent]:
    """Return at most 100 events, newest first, within one validated scope."""
    if not 1 <= limit <= 100:
        raise _invalid_event("Runtime event retrieval limit must be between 1 and 100")
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if workspace is None:
        raise _not_found()
    return await repository.list_recent_events(
        session, tenant_id=tenant_id, workspace_id=workspace_id, limit=limit
    )


async def validate_stream_scope(
    session: AsyncSession, *, tenant_id: UUID, workspace_id: UUID, cursor_id: UUID | None
) -> RuntimeEvent | None:
    """Validate a stream scope and resolve a cursor without cross-scope disclosure."""
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if workspace is None:
        raise _not_found()
    if cursor_id is None:
        return None
    cursor = await repository.get_scoped_event(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        event_id=cursor_id,
    )
    if cursor is None:
        raise _not_found()
    return cursor


async def list_stream_batch(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    cursor: RuntimeEvent | None,
    limit: int,
) -> list[RuntimeEvent]:
    """Read one bounded, deterministic stream batch within a validated scope."""
    if not 1 <= limit <= 100:
        raise _invalid_event("Runtime event retrieval limit must be between 1 and 100")
    if cursor is None:
        events = await repository.list_recent_events(
            session, tenant_id=tenant_id, workspace_id=workspace_id, limit=limit
        )
        return list(reversed(events))
    return await repository.list_events_after(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        occurred_at=cursor.occurred_at,
        event_id=cursor.id,
        limit=limit,
    )
