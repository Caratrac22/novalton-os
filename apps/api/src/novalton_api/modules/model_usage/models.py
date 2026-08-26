"""Persistent model-run accounting model."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class ModelRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One scoped provider invocation's durable accounting facts."""

    __tablename__ = "model_runs"
    __table_args__ = (
        CheckConstraint(
            "char_length(provider_id) BETWEEN 1 AND 64", name="ck_model_runs_provider_id_length"
        ),
        CheckConstraint(
            "char_length(provider_model_id) BETWEEN 1 AND 256",
            name="ck_model_runs_provider_model_id_length",
        ),
        CheckConstraint(
            "provider_resolved_model_id IS NULL OR char_length(provider_resolved_model_id) "
            "BETWEEN 1 AND 256",
            name="ck_model_runs_provider_resolved_model_id_length",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_model_runs_status_value",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_model_runs_correlation_id_length",
        ),
        CheckConstraint(
            "provider_request_id IS NULL OR char_length(provider_request_id) BETWEEN 1 AND 128",
            name="ck_model_runs_provider_request_id_length",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_model_runs_input_tokens_non_negative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_model_runs_output_tokens_non_negative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_model_runs_total_tokens_non_negative",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR output_tokens IS NULL OR total_tokens IS NULL "
            "OR total_tokens = input_tokens + output_tokens",
            name="ck_model_runs_total_tokens_consistent",
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ck_model_runs_estimated_cost_non_negative",
        ),
        CheckConstraint(
            "actual_cost IS NULL OR actual_cost >= 0", name="ck_model_runs_actual_cost_non_negative"
        ),
        CheckConstraint(
            "input_price_per_million_snapshot IS NULL OR input_price_per_million_snapshot >= 0",
            name="ck_model_runs_input_price_snapshot_non_negative",
        ),
        CheckConstraint(
            "output_price_per_million_snapshot IS NULL OR output_price_per_million_snapshot >= 0",
            name="ck_model_runs_output_price_snapshot_non_negative",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_model_runs_duration_non_negative"
        ),
        CheckConstraint(
            "failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 64",
            name="ck_model_runs_failure_code_length",
        ),
        CheckConstraint(
            "currency IS NULL OR char_length(currency) = 3", name="ck_model_runs_currency_length"
        ),
        CheckConstraint(
            "(estimated_cost IS NULL AND actual_cost IS NULL AND "
            "input_price_per_million_snapshot IS NULL AND "
            "output_price_per_million_snapshot IS NULL) OR currency IS NOT NULL",
            name="ck_model_runs_money_currency",
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND failure_code IS NULL) OR "
            "(status = 'SUCCEEDED' AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
            "(status = 'FAILED' AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
            "(status = 'CANCELLED' AND completed_at IS NOT NULL "
            "AND failure_code = 'cancellation')",
            name="ck_model_runs_lifecycle_shape",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_model_runs_timestamp_order",
        ),
        Index("ix_model_runs_scope_created", "tenant_id", "workspace_id", "created_at", "id"),
        Index("ix_model_runs_agent_run_created", "agent_run_id", "created_at", "id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_model_runs_tenant_id_tenants", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "workspaces.id", name="fk_model_runs_workspace_id_workspaces", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_model_runs_project_id_projects", ondelete="RESTRICT"),
        nullable=True,
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "agent_runs.id", name="fk_model_runs_agent_run_id_agent_runs", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    model_definition_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "model_definitions.id",
            name="fk_model_runs_model_definition_id_model_definitions",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    provider_resolved_model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    input_price_per_million_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10), nullable=True
    )
    output_price_per_million_snapshot: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10), nullable=True
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    duration_ms: Mapped[Decimal | None] = mapped_column(Numeric(20, 3), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
