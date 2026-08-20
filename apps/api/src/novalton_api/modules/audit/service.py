"""Audit validation, scoping, safe metadata, and transaction boundaries."""

import json
import logging
import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.context import get_correlation_id
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit import repository
from novalton_api.modules.audit.models import AuditRecord
from novalton_api.modules.audit.schemas import (
    ACTION_PATTERN,
    MAX_METADATA_BYTES,
    AuditRecordCreate,
)
from novalton_api.modules.projects import repository as projects_repository
from novalton_api.modules.tasks import repository as tasks_repository
from novalton_api.modules.workspaces.queries import get_workspace_by_tenant_and_id

logger = logging.getLogger(__name__)
_MAX_METADATA_DEPTH = 4
_MAX_METADATA_ITEMS = 64
_MAX_STRING_LENGTH = 256
_FORBIDDEN_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "authorizationheader",
    "body",
    "clientsecret",
    "cookie",
    "credential",
    "email",
    "idtoken",
    "message",
    "password",
    "passwd",
    "refreshtoken",
    "requestbody",
    "secret",
    "setcookie",
    "token",
}
_SECRET_VALUE_PATTERN = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/-]+=*|\bBasic\s+[A-Za-z0-9+/]+=*|\bsk-[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)


def _invalid_audit(message: str) -> ApplicationError:
    return ApplicationError("invalid_audit_record", message, status_code=422)


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


def _validate_metadata_value(value: Any, *, depth: int, item_count: list[int]) -> None:
    if depth > _MAX_METADATA_DEPTH:
        raise _invalid_audit("Audit metadata is too deeply nested")
    item_count[0] += 1
    if item_count[0] > _MAX_METADATA_ITEMS:
        raise _invalid_audit("Audit metadata contains too many values")
    if value is None or isinstance(value, bool | int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid_audit("Audit metadata contains a non-finite number")
        return
    if isinstance(value, str):
        if len(value) > _MAX_STRING_LENGTH:
            raise _invalid_audit("Audit metadata contains an oversized string")
        if _credential_bearing_url(value) or _SECRET_VALUE_PATTERN.search(value):
            raise _invalid_audit("Audit metadata contains credential material")
        return
    if isinstance(value, list):
        for item in value:
            _validate_metadata_value(item, depth=depth + 1, item_count=item_count)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid_audit("Audit metadata keys must be strings")
            if _forbidden_key(key):
                raise _invalid_audit("Audit metadata contains a forbidden field")
            _validate_metadata_value(item, depth=depth + 1, item_count=item_count)
        return
    raise _invalid_audit("Audit metadata contains a non-JSON value")


def safe_metadata(metadata: dict[str, Any] | None) -> dict[str, object] | None:
    """Validate and normalize a deliberately small, secret-free metadata object."""
    if metadata is None:
        return None
    _validate_metadata_value(metadata, depth=0, item_count=[0])
    try:
        encoded = json.dumps(
            metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _invalid_audit("Audit metadata is not JSON serializable") from None
    if len(encoded) > MAX_METADATA_BYTES:
        raise _invalid_audit("Audit metadata exceeds 4096 bytes")
    return json.loads(encoded)


async def _validate_scope(session: AsyncSession, data: AuditRecordCreate) -> None:
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=data.tenant_id, workspace_id=data.workspace_id
    )
    if workspace is None:
        raise _not_found()
    if (data.resource_type is None) != (data.resource_id is None):
        raise _invalid_audit("resource_type and resource_id must be supplied together")
    if data.task_id is not None and data.project_id is None:
        raise _invalid_audit("task_id requires project_id")
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
    if data.resource_type == "project" and data.resource_id != data.project_id:
        raise _invalid_audit("project resource must match project_id")
    if data.resource_type == "task" and data.resource_id != data.task_id:
        raise _invalid_audit("task resource must match task_id")


async def append_record(
    session: AsyncSession,
    *,
    data: AuditRecordCreate,
    occurred_at: datetime | None = None,
    commit: bool = True,
) -> AuditRecord:
    """Append one audit record, optionally joining an existing business transaction."""
    try:
        metadata = safe_metadata(data.metadata)
        await _validate_scope(session, data)
        record = await repository.append_record(
            session,
            tenant_id=data.tenant_id,
            workspace_id=data.workspace_id,
            action=data.action,
            actor_type=data.actor_type,
            actor_id=data.actor_id,
            outcome=data.outcome,
            resource_type=data.resource_type,
            resource_id=data.resource_id,
            project_id=data.project_id,
            task_id=data.task_id,
            correlation_id=data.correlation_id or get_correlation_id(),
            occurred_at=occurred_at,
            metadata_json=metadata,
        )
        if commit:
            await session.commit()
            await session.refresh(record)
    except ApplicationError:
        await session.rollback()
        raise
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Audit persistence failed",
            extra={"event": "audit.persistence_failed", "exception_type": type(exc).__name__},
        )
        raise ApplicationError(
            "audit_persistence_failed", "Audit record could not be persisted", status_code=500
        ) from None
    return record


async def list_recent_records(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    limit: int = 50,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
) -> list[AuditRecord]:
    """Return at most 100 records, newest first, in one validated scope."""
    if not 1 <= limit <= 100:
        raise _invalid_audit("Audit retrieval limit must be between 1 and 100")
    if action is not None and ACTION_PATTERN.fullmatch(action) is None:
        raise _invalid_audit("action must be lowercase dot-separated identifiers")
    if resource_type not in {None, "project", "task"}:
        raise _invalid_audit("Unsupported resource_type")
    if resource_id is not None and resource_type is None:
        raise _invalid_audit("resource_id filter requires resource_type")
    workspace = await get_workspace_by_tenant_and_id(
        session, tenant_id=tenant_id, workspace_id=workspace_id
    )
    if workspace is None:
        raise _not_found()
    return await repository.list_recent_records(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )
