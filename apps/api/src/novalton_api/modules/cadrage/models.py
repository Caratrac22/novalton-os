"""Durable private conversations and ordered messages."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class CadrageConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cadrage_conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="CASCADE",
            name="fk_cadrage_project_scope",
        ),
        Index(
            "ix_cadrage_owner_project",
            "tenant_id",
            "workspace_id",
            "project_id",
            "owner_id",
            "created_at",
            "id",
        ),
        CheckConstraint(
            "status IN ('OPEN','NEEDS_MODEL','READY_FOR_REVIEW',"
            "'APPROVED','REJECTED','NEEDS_CHANGES')",
            name="ck_cadrage_status",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("human_operators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pending_request_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CadrageMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cadrage_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_cadrage_message_sequence"),
        UniqueConstraint("conversation_id", "client_request_id", name="uq_cadrage_client_request"),
        UniqueConstraint("reply_to_id", name="uq_cadrage_assistant_reply"),
        Index("ix_cadrage_messages_page", "conversation_id", "sequence"),
        CheckConstraint("role IN ('USER','ASSISTANT')", name="ck_cadrage_role"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 4000", name="ck_cadrage_content"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cadrage_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    client_request_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    reply_to_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cadrage_messages.id", ondelete="SET NULL")
    )
