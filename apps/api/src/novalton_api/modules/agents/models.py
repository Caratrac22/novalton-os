"""Persistent, versioned agent definitions and scoped agent runs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class AgentDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable operational version of a workspace agent role."""

    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "slug",
            "version",
            name="uq_agent_definitions_scope_slug_version",
        ),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120", name="ck_agent_definitions_name_length"
        ),
        CheckConstraint("slug ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_agent_definitions_slug_format"),
        CheckConstraint("version > 0", name="ck_agent_definitions_version_positive"),
        CheckConstraint(
            "status IN ('ENABLED', 'DISABLED', 'ARCHIVED')",
            name="ck_agent_definitions_status_value",
        ),
        CheckConstraint(
            "category IS NULL OR char_length(category) BETWEEN 1 AND 64",
            name="ck_agent_definitions_category_length",
        ),
        CheckConstraint(
            "char_length(mission) BETWEEN 1 AND 2000", name="ck_agent_definitions_mission_length"
        ),
        CheckConstraint(
            "cardinality(capabilities) <= 32", name="ck_agent_definitions_capabilities_count"
        ),
        CheckConstraint(
            "cardinality(permissions) <= 32", name="ck_agent_definitions_permissions_count"
        ),
        Index(
            "ix_agent_definitions_scope_created", "tenant_id", "workspace_id", "created_at", "id"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mission: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False)


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lifecycle metadata for one isolated use of an exact definition version."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("agent_version > 0", name="ck_agent_runs_version_positive"),
        CheckConstraint(
            "char_length(agent_name) BETWEEN 1 AND 120", name="ck_agent_runs_name_length"
        ),
        CheckConstraint("agent_slug ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_agent_runs_slug_format"),
        CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'WAITING_FOR_APPROVAL', "
            "'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_agent_runs_status_value",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_agent_runs_correlation_id_length",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_agent_runs_failure_code_format",
        ),
        CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL", name="ck_agent_runs_task_requires_project"
        ),
        CheckConstraint(
            "parent_agent_run_id IS NULL OR parent_agent_run_id <> id",
            name="ck_agent_runs_parent_not_self",
        ),
        CheckConstraint(
            "(status = 'CREATED' AND started_at IS NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'WAITING_FOR_APPROVAL' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'SUCCEEDED' "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) "
            "OR (status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL) OR (status = 'CANCELLED' AND completed_at IS NOT NULL "
            "AND failure_code IS NULL)",
            name="ck_agent_runs_lifecycle_shape",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_agent_runs_timestamp_order",
        ),
        Index("ix_agent_runs_scope_created", "tenant_id", "workspace_id", "created_at", "id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True
    )
    agent_definition_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    model_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("model_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    parent_agent_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
