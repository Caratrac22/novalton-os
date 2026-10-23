"""Durable private conversations and ordered messages."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
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


class CadrageSpecification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable snapshots; one document with monotone versions per conversation."""

    __tablename__ = "cadrage_specifications"
    __table_args__ = (
        UniqueConstraint("conversation_id", "version", name="uq_cadrage_spec_version"),
        CheckConstraint("version > 0", name="ck_cadrage_spec_version"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cadrage_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    editor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("human_operators.id", ondelete="RESTRICT"),
        nullable=False,
    )


class CadragePlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable plan content tied to a spec snapshot; human decision is separate state."""

    __tablename__ = "cadrage_plans"
    __table_args__ = (
        UniqueConstraint("specification_id", name="uq_cadrage_plan_specification"),
        CheckConstraint(
            "status IN ('DRAFT','READY_FOR_REVIEW','APPROVED',"
            "'REJECTED','NEEDS_CHANGES','SUPERSEDED')",
            name="ck_cadrage_plan_status",
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cadrage_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    specification_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cadrage_specifications.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    decided_by: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("human_operators.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
