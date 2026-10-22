"""SQL scoped, ordered and idempotent human-owned project conversations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from novalton_api.core.exceptions import ApplicationError
from novalton_api.modules.audit.schemas import AuditRecordCreate
from novalton_api.modules.audit.service import append_record
from novalton_api.modules.cadrage.models import CadrageConversation, CadrageMessage
from novalton_api.modules.projects import service as projects_service


def _missing() -> ApplicationError:
    return ApplicationError("resource_not_found", "Resource not found", status_code=404)


async def get_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    conversation_id: UUID,
    lock: bool = False,
) -> CadrageConversation:
    statement = select(CadrageConversation).where(
        CadrageConversation.id == conversation_id,
        CadrageConversation.tenant_id == tenant_id,
        CadrageConversation.workspace_id == workspace_id,
        CadrageConversation.project_id == project_id,
        CadrageConversation.owner_id == owner_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement.execution_options(populate_existing=True))
    if row is None:
        raise _missing()
    return row


async def create_conversation(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    title: str,
) -> CadrageConversation:
    project = await projects_service.get_project(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    if project.status != "ACTIVE":
        raise ApplicationError("project_inactive", "Project is not active", status_code=409)
    row = CadrageConversation(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        project_id=project_id,
        owner_id=owner_id,
        title=title.strip(),
        status="OPEN",
        next_sequence=1,
    )
    session.add(row)
    await session.flush()
    await append_record(
        session,
        data=AuditRecordCreate(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            action="cadrage.conversation.create",
            actor_type="local_user",
            actor_id=str(owner_id),
            outcome="success",
            resource_type="project",
            resource_id=project_id,
            project_id=project_id,
            metadata={"conversation_id": str(row.id)},
        ),
        commit=False,
    )
    await session.commit()
    return row


async def list_conversations(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    limit: int,
    offset: int,
) -> list[CadrageConversation]:
    await projects_service.get_project(
        session, tenant_id=tenant_id, workspace_id=workspace_id, project_id=project_id
    )
    return list(
        (
            await session.scalars(
                select(CadrageConversation)
                .where(
                    CadrageConversation.tenant_id == tenant_id,
                    CadrageConversation.workspace_id == workspace_id,
                    CadrageConversation.project_id == project_id,
                    CadrageConversation.owner_id == owner_id,
                )
                .order_by(CadrageConversation.created_at.desc(), CadrageConversation.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )


async def list_messages(
    session: AsyncSession, *, conversation: CadrageConversation, after: int, limit: int
) -> list[CadrageMessage]:
    return list(
        (
            await session.scalars(
                select(CadrageMessage)
                .where(
                    CadrageMessage.conversation_id == conversation.id,
                    CadrageMessage.sequence > after,
                )
                .order_by(CadrageMessage.sequence)
                .limit(limit)
            )
        ).all()
    )


async def append_user_message(
    session: AsyncSession,
    *,
    conversation: CadrageConversation,
    content: str,
    request_id: UUID,
    reserve_for_model: bool = False,
) -> tuple[CadrageMessage, bool]:
    # Caller locked the conversation row: sequence and dedupe are serialized.
    existing = await session.scalar(
        select(CadrageMessage).where(
            CadrageMessage.conversation_id == conversation.id,
            CadrageMessage.client_request_id == request_id,
        )
    )
    if existing is not None:
        if existing.content != content or existing.role != "USER":
            raise ApplicationError("request_id_conflict", "Request ID reused", status_code=409)
        return existing, False
    if conversation.pending_request_id is not None:
        raise ApplicationError("generation_in_progress", "Answer in progress", status_code=409)
    if conversation.status in {"APPROVED", "READY_FOR_REVIEW"}:
        raise ApplicationError("conversation_locked", "Review requires changes", status_code=409)
    row = CadrageMessage(
        conversation_id=conversation.id,
        sequence=conversation.next_sequence,
        role="USER",
        content=content,
        client_request_id=request_id,
    )
    conversation.next_sequence += 1
    conversation.status = "NEEDS_MODEL"
    if reserve_for_model:
        # Reserve under the same row lock as insertion. Another send cannot
        # overtake an in-flight answer between these two decisions.
        conversation.pending_request_id = request_id
        conversation.pending_since = datetime.now(UTC)
    session.add(row)
    await session.commit()
    return row, True


async def assistant_reply(
    session: AsyncSession, *, conversation: CadrageConversation, user_message: CadrageMessage
) -> CadrageMessage | None:
    return await session.scalar(
        select(CadrageMessage).where(
            CadrageMessage.conversation_id == conversation.id,
            CadrageMessage.reply_to_id == user_message.id,
        )
    )


async def reserve_reply(
    session: AsyncSession, *, conversation: CadrageConversation, user_message: CadrageMessage
) -> bool:
    if await assistant_reply(session, conversation=conversation, user_message=user_message):
        return False
    if conversation.pending_request_id is not None and (
        conversation.pending_request_id != user_message.client_request_id
        or conversation.pending_since is None
        or conversation.pending_since + timedelta(minutes=2) > datetime.now(UTC)
    ):
        return False
    conversation.pending_request_id = user_message.client_request_id
    conversation.pending_since = datetime.now(UTC)
    await session.commit()
    return True


async def finish_reply(
    session: AsyncSession,
    *,
    conversation: CadrageConversation,
    user_message: CadrageMessage,
    content: str | None,
) -> CadrageMessage | None:
    if conversation.pending_request_id != user_message.client_request_id:
        return await assistant_reply(session, conversation=conversation, user_message=user_message)
    conversation.pending_request_id = None
    conversation.pending_since = None
    if content is None:
        conversation.status = "NEEDS_MODEL"
        await session.commit()
        return None
    row = CadrageMessage(
        conversation_id=conversation.id,
        sequence=conversation.next_sequence,
        role="ASSISTANT",
        content=content,
        reply_to_id=user_message.id,
    )
    conversation.next_sequence += 1
    conversation.status = "OPEN"
    session.add(row)
    await session.commit()
    return row
