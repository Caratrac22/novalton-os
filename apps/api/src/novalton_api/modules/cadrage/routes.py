"""Human-owned project chat; no API here may enqueue or advance a workflow."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.cadrage import service
from novalton_api.modules.cadrage.generation import generate_reply
from novalton_api.modules.cadrage.models import CadrageConversation, CadrageMessage
from novalton_api.modules.durable_dispatch.operator import OperatorAuthority
from novalton_api.modules.durable_dispatch.saas_access import require_saas_access
from novalton_api.modules.projects import service as projects_service

router = APIRouter(
    prefix="/tenants/{tenant_id}/workspaces/{workspace_id}/projects/{project_id}/conversations",
    tags=["cadrage"],
)
Session = Annotated[AsyncSession, Depends(get_async_session)]
Human = Annotated[OperatorAuthority | None, Depends(require_saas_access)]


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content: str = Field(min_length=1, max_length=4000)
    client_request_id: UUID = Field(strict=False)


def _human(operator: OperatorAuthority | None) -> OperatorAuthority:
    if operator is None:
        raise ApplicationError("saas_auth_required", "Session required", status_code=401)
    return operator


def _conversation(row: CadrageConversation) -> dict[str, object]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "status": row.status,
        "created_at": row.created_at,
    }


def _message(row: CadrageMessage) -> dict[str, object]:
    return {
        "id": row.id,
        "sequence": row.sequence,
        "role": row.role,
        "content": row.content,
        "created_at": row.created_at,
    }


@router.post("", status_code=201)
async def create(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    data: ConversationInput,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    row = await service.create_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_id=_human(operator).user_id,
        title=data.title,
    )
    return _conversation(row)


@router.get("")
async def listing(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    session: Session,
    operator: Human,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> dict[str, object]:
    rows = await service.list_conversations(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_id=_human(operator).user_id,
        limit=limit,
        offset=offset,
    )
    return {"items": [_conversation(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/model/config")
async def model_config(
    tenant_id: UUID, workspace_id: UUID, project_id: UUID, session: Session, operator: Human
) -> dict[str, object]:
    _human(operator)
    await projects_service.get_project(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    settings = get_settings()
    return {
        "policy": settings.cadrage_model_policy,
        "local": {
            "provider": "local_cadrage",
            "model": settings.local_model_id,
            "configured": settings.local_model_id is not None,
            "endpoint_kind": "LM Studio / Ollama OpenAI-compatible",
            "cost_possible": False,
        },
        "external": {
            "provider": settings.openai_compatible_provider_id,
            "configured": settings.openai_compatible_base_url is not None
            and settings.openai_compatible_api_key is not None,
            "chat_enabled": False,
            "cost_possible": True,
            "key_storage": "server environment only",
        },
        "selection": "local only; no paid fallback",
    }


@router.get("/{conversation_id}")
async def detail(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    row = await service.get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=_human(operator).user_id,
    )
    return _conversation(row)


@router.get("/{conversation_id}/messages")
async def messages(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    session: Session,
    operator: Human,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    row = await service.get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=_human(operator).user_id,
    )
    entries = await service.list_messages(session, conversation=row, after=after, limit=limit)
    return {
        "items": [_message(item) for item in entries],
        "next_after": entries[-1].sequence if entries else after,
    }


@router.post("/{conversation_id}/messages", status_code=201)
async def send(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    data: MessageInput,
    session: Session,
    operator: Human,
    request: Request,
) -> dict[str, object]:
    if not data.content.strip():
        raise ApplicationError("invalid_message", "Message is empty", status_code=422)
    row = await service.get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=_human(operator).user_id,
        lock=True,
    )
    settings = get_settings()
    message, created = await service.append_user_message(
        session,
        conversation=row,
        content=data.content.strip(),
        request_id=data.client_request_id,
        reserve_for_model=settings.local_model_id is not None,
    )
    existing_reply = await service.assistant_reply(session, conversation=row, user_message=message)
    if existing_reply is not None:
        return {
            "message": _message(message),
            "created": created,
            "assistant": _message(existing_reply),
            "assistant_status": "AVAILABLE",
        }
    if settings.local_model_id is None:
        return {
            "message": _message(message),
            "created": created,
            "assistant": None,
            "assistant_status": "MODEL_UNAVAILABLE",
        }
    row = await service.get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=_human(operator).user_id,
        lock=True,
    )
    if not created and not await service.reserve_reply(
        session, conversation=row, user_message=message
    ):
        return {
            "message": _message(message),
            "created": created,
            "assistant": None,
            "assistant_status": "PROCESSING",
        }
    history = await service.list_messages(
        session, conversation=row, after=max(0, message.sequence - 16), limit=17
    )
    title = row.title
    await session.commit()  # Release the read transaction before bounded model network IO.
    try:
        answer = await generate_reply(
            request.app.state.provider_registry,
            model_id=settings.local_model_id,
            title=title,
            history=history,
        )
    except Exception:
        answer = None
    # A revoked session or grant cannot persist a late model result.
    await _human(operator).require_human(
        session, "workspace.write", tenant_id=tenant_id, workspace_id=workspace_id
    )
    row = await service.get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=_human(operator).user_id,
        lock=True,
    )
    assistant = await service.finish_reply(
        session, conversation=row, user_message=message, content=answer
    )
    return {
        "message": _message(message),
        "created": created,
        "assistant": _message(assistant) if assistant is not None else None,
        "assistant_status": "AVAILABLE" if assistant is not None else "PROVIDER_ERROR",
    }
