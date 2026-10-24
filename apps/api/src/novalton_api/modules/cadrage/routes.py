"""Human-owned project chat; no API here may enqueue or advance a workflow."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.config import get_settings
from novalton_api.core.database import get_async_session
from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.cadrage import compilation as compilation_service
from novalton_api.modules.cadrage import plan as plan_service
from novalton_api.modules.cadrage import service
from novalton_api.modules.cadrage.generation import generate_reply
from novalton_api.modules.cadrage.models import (
    CadrageCompilation,
    CadrageConversation,
    CadrageMessage,
    CadragePlan,
    CadrageSpecification,
)
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


class SpecificationItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topic: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.-]*$")
    value: str = Field(min_length=1, max_length=2000)
    provenance: str = Field(pattern="^(USER|MODEL_PROPOSAL|INFERENCE)$")
    state: str = Field(pattern="^(PROPOSED|CONFIRMED|CONFLICT|OPEN)$")


class SpecificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    summary: str = Field(max_length=3000)
    items: list[SpecificationItem] = Field(max_length=100)


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_specification_version: int = Field(ge=1)


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: str = Field(pattern="^(READY_FOR_REVIEW|APPROVED|REJECTED|NEEDS_CHANGES)$")


class CompilationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: UUID


def _compilation(row: CadrageCompilation) -> dict[str, object]:
    return {
        "id": row.id,
        "plan_id": row.plan_id,
        "task_id": row.task_id,
        "source_version": row.source_version,
        "proposal_version": row.proposal_version,
        "status": row.status,
        "document": row.document,
        "created_at": row.created_at,
    }


def _plan(row: CadragePlan) -> dict[str, object]:
    return {
        "id": row.id,
        "specification_id": row.specification_id,
        "source_version": row.source_version,
        "document": row.document,
        "status": row.status,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at,
        "created_at": row.created_at,
    }


@router.get("/{conversation_id}/plans")
async def plans(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    from sqlalchemy import select

    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id
    )
    rows = (
        await session.scalars(
            select(CadragePlan)
            .where(CadragePlan.conversation_id == conversation.id)
            .order_by(CadragePlan.source_version.desc())
            .limit(50)
        )
    ).all()
    return {"items": [_plan(row) for row in rows]}


@router.post("/{conversation_id}/plans", status_code=201)
async def prepare_plan(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    data: PlanInput,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id, lock=True
    )
    row = await plan_service.create_plan(
        session,
        conversation=conversation,
        expected_version=data.expected_specification_version,
        owner=_human(operator).user_id,
    )
    return _plan(row)


@router.post("/{conversation_id}/plans/{plan_id}/decision")
async def plan_decision(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    data: PlanDecision,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id, lock=True
    )
    row = await plan_service.get_plan(
        session, conversation=conversation, plan_id=plan_id, lock=True
    )
    return _plan(
        await plan_service.decide(
            session,
            conversation=conversation,
            plan=row,
            owner=_human(operator).user_id,
            decision=data.decision,
        )
    )


@router.post("/{conversation_id}/plans/{plan_id}/compilations", status_code=201)
async def compile_approved_plan(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    data: CompilationInput,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id, lock=True
    )
    plan = await plan_service.get_plan(
        session, conversation=conversation, plan_id=plan_id, lock=True
    )
    row = await compilation_service.compile_plan(
        session,
        conversation=conversation,
        plan=plan,
        task_id=data.task_id,
        owner=_human(operator).user_id,
    )
    return _compilation(row)


@router.get("/{conversation_id}/plans/{plan_id}/compilations/{compilation_id}/preflight")
async def compilation_preflight(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    plan_id: UUID,
    compilation_id: UUID,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    from sqlalchemy import select

    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id
    )
    plan = await plan_service.get_plan(session, conversation=conversation, plan_id=plan_id)
    row = await session.scalar(
        select(CadrageCompilation).where(
            CadrageCompilation.id == compilation_id,
            CadrageCompilation.plan_id == plan.id,
            CadrageCompilation.owner_id == _human(operator).user_id,
        )
    )
    if row is None:
        raise plan_service.missing()
    return {
        "compilation": _compilation(row),
        "preflight": await compilation_service.preflight(
            session, conversation=conversation, plan=plan, compilation=row
        ),
    }


def _spec(row: CadrageSpecification) -> dict[str, object]:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "version": row.version,
        "document": row.document,
        "source": row.source,
        "editor_id": row.editor_id,
        "created_at": row.created_at,
    }


async def _scoped_conversation(
    session: AsyncSession,
    operator: OperatorAuthority | None,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    *,
    lock: bool = False,
) -> CadrageConversation:
    return await service.get_conversation(
        session,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        conversation_id=conversation_id,
        owner_id=_human(operator).user_id,
        lock=lock,
    )


@router.get("/{conversation_id}/specifications")
async def specification_versions(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    session: Session,
    operator: Human,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> dict[str, object]:
    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id
    )
    rows = await service.list_specifications(session, conversation, limit=limit, offset=offset)
    return {"items": [_spec(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/{conversation_id}/specifications/{version}")
async def specification_version(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    version: int,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id
    )
    from sqlalchemy import select

    row = await session.scalar(
        select(CadrageSpecification).where(
            CadrageSpecification.conversation_id == conversation.id,
            CadrageSpecification.version == version,
        )
    )
    if row is None:
        raise service._missing()
    return _spec(row)


@router.put("/{conversation_id}/specifications")
async def specification_update(
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    conversation_id: UUID,
    data: SpecificationInput,
    session: Session,
    operator: Human,
) -> dict[str, object]:
    conversation = await _scoped_conversation(
        session, operator, tenant_id, workspace_id, project_id, conversation_id, lock=True
    )
    if conversation.pending_request_id is not None:
        # The generation may finish only against its prior snapshot; a manual edit wins.
        conversation.pending_request_id = None
        conversation.pending_since = None
    document = {"summary": data.summary, "items": [entry.model_dump() for entry in data.items]}
    row = await service.save_specification(
        session,
        conversation=conversation,
        expected_version=data.expected_version,
        document=document,
        editor_id=_human(operator).user_id,
    )
    return _spec(row)


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
    current_spec = await service.current_specification(session, row)
    spec_version = current_spec.version if current_spec else 0
    spec_document = current_spec.document if current_spec else None
    await session.commit()  # Release the read transaction before bounded model network IO.
    try:
        answer, proposals = await generate_reply(
            request.app.state.provider_registry,
            model_id=settings.local_model_id,
            title=title,
            history=history,
            specification=spec_document,
        )
    except Exception:
        answer = None
        proposals = []
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
    if row.pending_request_id == message.client_request_id and proposals:
        latest = await service.current_specification(session, row)
        if (latest.version if latest else 0) == spec_version:
            previous = latest.document if latest else {"summary": "", "items": []}
            items = list(previous["items"])
            # A model may suggest new facts; it cannot replace a human's confirmed correction.
            known = {item["topic"]: item["value"] for item in items}
            for proposal in proposals:
                if len(items) >= 100:
                    break
                topic = proposal["topic"]
                if topic not in known:
                    items.append({**proposal, "provenance": "MODEL_PROPOSAL", "state": "PROPOSED"})
                    known[topic] = proposal["value"]
                elif known[topic] != proposal["value"]:
                    conflict_topic = f"conflict.{topic}"
                    if len(conflict_topic) <= 80 and conflict_topic not in known:
                        items.append(
                            {
                                "topic": conflict_topic,
                                "value": proposal["value"],
                                "provenance": "MODEL_PROPOSAL",
                                "state": "CONFLICT",
                            }
                        )
                        known[conflict_topic] = proposal["value"]
            if len(items) != len(previous["items"]):
                await service.save_specification(
                    session,
                    conversation=row,
                    expected_version=spec_version,
                    document={"summary": previous["summary"], "items": items},
                    editor_id=_human(operator).user_id,
                    source="MODEL",
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
