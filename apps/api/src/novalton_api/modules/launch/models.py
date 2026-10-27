"""Revocable human decision bound to a single immutable cadrage proposal."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class LaunchAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "launch_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT",
            name="fk_launch_project_scope",
        ),
        UniqueConstraint("owner_id", "request_id", name="uq_launch_owner_request"),
        UniqueConstraint("workflow_run_id", name="uq_launch_workflow_run"),
        Index(
            "uq_launch_compilation_workflow",
            "compilation_id",
            unique=True,
            postgresql_where=text("workflow_run_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(workflow_plan_id IS NULL AND workflow_run_id IS NULL AND "
            "launch_request_id IS NULL AND dispatch_generation IS NULL) OR "
            "(workflow_plan_id IS NOT NULL AND workflow_run_id IS NOT NULL AND "
            "launch_request_id IS NOT NULL AND dispatch_generation > 0)",
            name="ck_launch_workflow_binding_complete",
        ),
        CheckConstraint(
            "source_version > 0 AND proposal_version > 0 AND version > 0", name="ck_launch_versions"
        ),
        CheckConstraint(
            "max_model_calls BETWEEN 1 AND 100 AND max_duration_seconds BETWEEN 1 AND 3600",
            name="ck_launch_limits",
        ),
        CheckConstraint("environment = 'DISPOSABLE_TEST'", name="ck_launch_environment"),
        CheckConstraint(
            "provider_id = 'local' AND char_length(model_id) BETWEEN 1 AND 256",
            name="ck_launch_local_model",
        ),
        CheckConstraint("char_length(fingerprint) = 64", name="ck_launch_fingerprint"),
        CheckConstraint("expires_at > created_at", name="ck_launch_expiry"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("human_operators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cadrage_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    compilation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cadrage_compilations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    max_model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    financial_authorization_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("financial_authorizations.id", ondelete="RESTRICT")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workflow_plan_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("workflow_plans.id", ondelete="RESTRICT")
    )
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="RESTRICT")
    )
    launch_request_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    dispatch_generation: Mapped[int | None] = mapped_column(Integer)
