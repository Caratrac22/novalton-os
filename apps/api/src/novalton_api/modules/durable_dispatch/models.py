"""Scheduling evidence; workflow, provider and tool records remain execution truth."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class DispatchActivation(TimestampMixin, Base):
    __tablename__ = "dispatch_activations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "tenant_id", name="uq_dispatch_activation_scope"),
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_dispatch_activation_workspace_scope",
        ),
        CheckConstraint("generation > 0", name="ck_dispatch_activation_generation"),
    )
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TaskDispatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "task_dispatches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "request_key", name="uq_dispatch_request"),
        UniqueConstraint("workflow_run_id", name="uq_dispatch_workflow_binding"),
        UniqueConstraint("id", "tenant_id", "workspace_id", name="uq_dispatch_id_scope"),
        UniqueConstraint("id", "workflow_run_id", name="uq_dispatch_id_workflow"),
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["dispatch_activations.workspace_id", "dispatch_activations.tenant_id"],
            ondelete="RESTRICT",
            name="fk_dispatch_activation_scope",
        ),
        ForeignKeyConstraint(
            ["workflow_run_id", "tenant_id", "workspace_id", "project_id", "task_id"],
            [
                "workflow_runs.id", "workflow_runs.tenant_id", "workflow_runs.workspace_id",
                "workflow_runs.project_id", "workflow_runs.task_id",
            ],
            ondelete="RESTRICT",
            name="fk_dispatch_workflow_scope",
        ),
        CheckConstraint(
            "status IN ('READY','LEASED','WAITING_HUMAN','BLOCKED','DONE','CANCELLED')",
            name="ck_dispatch_status",
        ),
        CheckConstraint("priority BETWEEN -100 AND 100", name="ck_dispatch_priority"),
        CheckConstraint("request_key ~ '^[a-zA-Z0-9_.:-]{1,128}$'", name="ck_dispatch_request"),
        CheckConstraint("input_fingerprint ~ '^[a-f0-9]{64}$'", name="ck_dispatch_fingerprint"),
        CheckConstraint(
            "max_attempts BETWEEN 0 AND 64 AND attempt_count BETWEEN 0 AND max_attempts "
            "AND generation = attempt_count",
            name="ck_dispatch_attempt_budget",
        ),
        CheckConstraint(
            "max_model_calls BETWEEN 0 AND 128 "
            "AND model_call_count BETWEEN 0 AND max_model_calls",
            name="ck_dispatch_model_budget",
        ),
        CheckConstraint(
            "(status = 'LEASED' AND owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND activation_generation IS NOT NULL) OR (status <> 'LEASED' "
            "AND owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_dispatch_lease_shape",
        ),
        CheckConstraint(
            "stop_reason IS NULL OR stop_reason ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_dispatch_stop_reason",
        ),
        Index(
            "uq_dispatch_active_task", "tenant_id", "workspace_id", "task_id",
            unique=True,
            postgresql_where=text("status IN ('READY','LEASED','WAITING_HUMAN')"),
        ),
        Index(
            "ix_dispatch_claim", "tenant_id", "workspace_id", "status", "priority",
            "eligible_at", "id",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    model_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_unknown_cost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DispatchDependency(Base):
    __tablename__ = "dispatch_dependencies"
    __table_args__ = (
        CheckConstraint("dispatch_id <> prerequisite_id", name="ck_dispatch_dependency_not_self"),
        ForeignKeyConstraint(
            ["dispatch_id", "tenant_id", "workspace_id"],
            ["task_dispatches.id", "task_dispatches.tenant_id", "task_dispatches.workspace_id"],
            ondelete="RESTRICT",
            name="fk_dispatch_dependency_scope",
        ),
        ForeignKeyConstraint(
            ["prerequisite_id", "tenant_id", "workspace_id"],
            ["task_dispatches.id", "task_dispatches.tenant_id", "task_dispatches.workspace_id"],
            ondelete="RESTRICT",
            name="fk_dispatch_prerequisite_scope",
        ),
    )
    dispatch_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    prerequisite_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)


class DispatchAttempt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "dispatch_attempts"
    __table_args__ = (
        UniqueConstraint("dispatch_id", "generation", name="uq_dispatch_attempt_generation"),
        ForeignKeyConstraint(
            ["dispatch_id", "workflow_run_id"],
            ["task_dispatches.id", "task_dispatches.workflow_run_id"],
            ondelete="RESTRICT",
            name="fk_dispatch_attempt_binding",
        ),
        CheckConstraint("generation > 0", name="ck_dispatch_attempt_generation"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('READY','WAITING_HUMAN','BLOCKED','DONE','CANCELLED')",
            name="ck_dispatch_attempt_outcome",
        ),
        CheckConstraint(
            "(outcome IS NULL AND completed_at IS NULL) OR "
            "(outcome IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_dispatch_attempt_completion",
        ),
        CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_dispatch_attempt_reason",
        ),
    )
    dispatch_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    owner: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pre_status: Mapped[str] = mapped_column(String(16), nullable=False)
    post_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    workflow_step_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("workflow_step_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
