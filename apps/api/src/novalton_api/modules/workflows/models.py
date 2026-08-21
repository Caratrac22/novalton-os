"""Persistent versioned workflow graphs and independent run state."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable, complete version of a task execution graph."""

    __tablename__ = "workflow_plans"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "task_id",
            "version",
            name="uq_workflow_plans_scope_task_version",
        ),
        CheckConstraint("version > 0", name="ck_workflow_plans_version_positive"),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_workflow_plans_title_length"
        ),
        CheckConstraint(
            "summary IS NULL OR char_length(summary) <= 2000",
            name="ck_workflow_plans_summary_length",
        ),
        CheckConstraint(
            "change_reason IS NULL OR char_length(change_reason) BETWEEN 1 AND 500",
            name="ck_workflow_plans_change_reason_length",
        ),
        CheckConstraint(
            "(version = 1 AND change_reason IS NULL) OR "
            "(version > 1 AND change_reason IS NOT NULL)",
            name="ck_workflow_plans_change_reason_version",
        ),
        Index(
            "ix_workflow_plans_scope_task_created",
            "tenant_id",
            "workspace_id",
            "task_id",
            "created_at",
            "id",
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
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="WorkflowStep.position"
    )


class WorkflowStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A descriptive node in one immutable plan version."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_plan_id", "step_key", name="uq_workflow_steps_plan_key"),
        UniqueConstraint("workflow_plan_id", "position", name="uq_workflow_steps_plan_position"),
        UniqueConstraint("id", "workflow_plan_id", name="uq_workflow_steps_id_plan"),
        CheckConstraint("step_key ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_workflow_steps_key_format"),
        CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_workflow_steps_title_length"
        ),
        CheckConstraint(
            "step_type IN ('AGENT_TASK', 'MANUAL_REVIEW', 'SYSTEM')",
            name="ck_workflow_steps_type_value",
        ),
        CheckConstraint(
            "assigned_capability IS NULL OR assigned_capability ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_workflow_steps_capability_format",
        ),
        CheckConstraint("position >= 0", name="ck_workflow_steps_position_nonnegative"),
        CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_workflow_steps_risk_value",
        ),
    )
    workflow_plan_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    step_type: Mapped[str] = mapped_column(String(24), nullable=False)
    assigned_capability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_definition_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_definitions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    plan: Mapped[WorkflowPlan] = relationship(back_populates="steps")


class WorkflowStepDependency(Base):
    """One normalized same-plan directed prerequisite edge."""

    __tablename__ = "workflow_step_dependencies"
    __table_args__ = (
        CheckConstraint(
            "workflow_step_id <> depends_on_step_id", name="ck_workflow_step_dependencies_not_self"
        ),
        ForeignKeyConstraint(
            ["workflow_step_id", "workflow_plan_id"],
            ["workflow_steps.id", "workflow_steps.workflow_plan_id"],
            name="fk_workflow_dependencies_step_plan",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["depends_on_step_id", "workflow_plan_id"],
            ["workflow_steps.id", "workflow_steps.workflow_plan_id"],
            name="fk_workflow_dependencies_prerequisite_plan",
            ondelete="CASCADE",
        ),
    )
    workflow_plan_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_plans.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workflow_step_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    depends_on_step_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One stateful use of an exact immutable plan version."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("id", "workflow_plan_id", name="uq_workflow_runs_id_plan"),
        CheckConstraint("plan_version > 0", name="ck_workflow_runs_plan_version_positive"),
        CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_workflow_runs_status_value",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_workflow_runs_correlation_length",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_workflow_runs_failure_format",
        ),
        CheckConstraint(
            "(status = 'CREATED' AND started_at IS NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'COMPLETED' "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) "
            "OR (status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL) OR (status = 'CANCELLED' "
            "AND completed_at IS NOT NULL AND failure_code IS NULL)",
            name="ck_workflow_runs_lifecycle_shape",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_workflow_runs_timestamp_order",
        ),
        Index("ix_workflow_runs_scope_created", "tenant_id", "workspace_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_plan_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowStepRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Independent runtime state for one plan step in one workflow run."""

    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "workflow_step_id", name="uq_workflow_step_runs_run_step"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'READY', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_workflow_step_runs_status_value",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_workflow_step_runs_failure_format",
        ),
        CheckConstraint(
            "(status IN ('PENDING', 'READY') AND started_at IS NULL AND completed_at IS NULL "
            "AND failure_code IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'COMPLETED' "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) "
            "OR (status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL) OR (status = 'CANCELLED' "
            "AND completed_at IS NOT NULL AND failure_code IS NULL)",
            name="ck_workflow_step_runs_lifecycle_shape",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_workflow_step_runs_timestamp_order",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "workflow_plan_id"],
            ["workflow_runs.id", "workflow_runs.workflow_plan_id"],
            name="fk_workflow_step_runs_run_plan",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workflow_step_id", "workflow_plan_id"],
            ["workflow_steps.id", "workflow_steps.workflow_plan_id"],
            name="fk_workflow_step_runs_step_plan",
            ondelete="RESTRICT",
        ),
        Index("ix_workflow_step_runs_run_status", "workflow_run_id", "status"),
    )
    workflow_run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workflow_plan_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workflow_step_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
