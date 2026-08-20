"""Append-only runtime event persistence model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import UUIDPrimaryKeyMixin


class RuntimeEvent(UUIDPrimaryKeyMixin, Base):
    """An immutable operational fact within an explicit tenant/workspace scope."""

    __tablename__ = "runtime_events"
    __table_args__ = (
        CheckConstraint(
            "char_length(event_type) BETWEEN 3 AND 100",
            name="ck_runtime_events_event_type_length",
        ),
        CheckConstraint(
            "char_length(source) BETWEEN 1 AND 64",
            name="ck_runtime_events_source_length",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_runtime_events_correlation_id_length",
        ),
        CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_runtime_events_task_requires_project",
        ),
        Index(
            "ix_runtime_events_scope_occurred_at_id",
            "tenant_id",
            "workspace_id",
            "occurred_at",
            "id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_runtime_events_tenant_id_tenants", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            name="fk_runtime_events_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            name="fk_runtime_events_project_id_projects",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", name="fk_runtime_events_task_id_tasks", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
