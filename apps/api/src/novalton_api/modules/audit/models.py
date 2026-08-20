"""Append-only audit record persistence model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import UUIDPrimaryKeyMixin


class AuditRecord(UUIDPrimaryKeyMixin, Base):
    """An immutable accountability fact in an explicit tenant/workspace scope."""

    __tablename__ = "audit_records"
    __table_args__ = (
        CheckConstraint(
            "char_length(action) BETWEEN 3 AND 100", name="ck_audit_records_action_length"
        ),
        CheckConstraint(
            "actor_type IN ('system', 'api', 'local_user', 'service')",
            name="ck_audit_records_actor_type_value",
        ),
        CheckConstraint(
            "actor_id IS NULL OR char_length(actor_id) BETWEEN 1 AND 128",
            name="ck_audit_records_actor_id_length",
        ),
        CheckConstraint(
            "outcome IN ('success', 'failure', 'blocked', 'cancelled')",
            name="ck_audit_records_outcome_value",
        ),
        CheckConstraint(
            "resource_type IS NULL OR resource_type IN ('project', 'task')",
            name="ck_audit_records_resource_type_value",
        ),
        CheckConstraint(
            "(resource_type IS NULL) = (resource_id IS NULL)",
            name="ck_audit_records_resource_pair",
        ),
        CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_audit_records_task_requires_project",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_audit_records_correlation_id_length",
        ),
        Index(
            "ix_audit_records_scope_occurred_at_id",
            "tenant_id",
            "workspace_id",
            "occurred_at",
            "id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_audit_records_tenant_id_tenants", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "workspaces.id", name="fk_audit_records_workspace_id_workspaces", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_audit_records_project_id_projects", ondelete="SET NULL"),
        nullable=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", name="fk_audit_records_task_id_tasks", ondelete="SET NULL"),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
