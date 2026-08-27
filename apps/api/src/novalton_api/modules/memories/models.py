"""Persistent structured memory and its normalized provenance."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novalton_api.modules.workspaces.models import Workspace


class MemoryRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A scoped, temporal interpretation backed by one or more sources."""

    __tablename__ = "memory_records"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('FACT', 'DECISION', 'PREFERENCE', 'CONSTRAINT', 'EVENT', 'NOTE')",
            name="ck_memory_records_kind_value",
        ),
        CheckConstraint(
            "knowledge_state IN ('CONFIRMED_FACT', 'OBSERVED_FACT', 'INFERENCE', "
            "'HYPOTHESIS', 'DISPUTED', 'OBSOLETE')",
            name="ck_memory_records_knowledge_state_value",
        ),
        CheckConstraint(
            "char_length(statement) BETWEEN 1 AND 2000",
            name="ck_memory_records_statement_length",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memory_records_confidence_range"
        ),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_memory_records_importance_range"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="ck_memory_records_valid_interval"
        ),
        CheckConstraint(
            "lifecycle IN ('ACTIVE', 'ARCHIVED')", name="ck_memory_records_lifecycle_value"
        ),
        CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_memory_records_task_requires_project",
        ),
        Index("ix_memory_records_workspace_created_id", "workspace_id", "created_at", "id"),
        Index("ix_memory_records_workspace_kind", "workspace_id", "kind"),
        Index("ix_memory_records_workspace_knowledge_state", "workspace_id", "knowledge_state"),
        Index("ix_memory_records_workspace_project", "workspace_id", "project_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    knowledge_state: Mapped[str] = mapped_column(String(24), nullable=False)
    statement: Mapped[str] = mapped_column(String(2000), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")

    workspace: Mapped["Workspace"] = relationship()
    provenance: Mapped[list["MemoryProvenance"]] = relationship(
        back_populates="memory", cascade="all, delete-orphan", passive_deletes=True
    )


class MemoryProvenance(UUIDPrimaryKeyMixin, Base):
    """One bounded reference to a source supporting a memory record."""

    __tablename__ = "memory_provenance"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('USER_STATEMENT', 'TOOL_OBSERVATION', 'DOCUMENT', "
            "'AGENT_RESULT', 'SYSTEM_EVENT', 'DERIVED_FROM_MEMORY', 'MANUAL_EDIT')",
            name="ck_memory_provenance_source_type_value",
        ),
        CheckConstraint(
            "source_reference_id IS NULL OR char_length(source_reference_id) BETWEEN 1 AND 256",
            name="ck_memory_provenance_source_reference_length",
        ),
    )

    memory_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("memory_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_reference_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    memory: Mapped[MemoryRecord] = relationship(back_populates="provenance")
