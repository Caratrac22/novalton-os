"""Add I-019 durable model-run usage accounting.

Revision ID: 20260820_0010
Revises: 20260820_0009
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0010"
down_revision: str = "20260820_0009"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the single authoritative model invocation accounting table."""
    op.create_table(
        "model_runs",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("provider_model_id", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(20, 10), nullable=True),
        sa.Column("actual_cost", sa.Numeric(20, 10), nullable=True),
        sa.Column(
            "input_price_per_million_snapshot", sa.Numeric(20, 10), nullable=True
        ),
        sa.Column(
            "output_price_per_million_snapshot", sa.Numeric(20, 10), nullable=True
        ),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("duration_ms", sa.Numeric(20, 3), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(provider_id) BETWEEN 1 AND 64",
            name="ck_model_runs_provider_id_length",
        ),
        sa.CheckConstraint(
            "char_length(provider_model_id) BETWEEN 1 AND 256",
            name="ck_model_runs_provider_model_id_length",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_model_runs_status_value",
        ),
        sa.CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_model_runs_correlation_id_length",
        ),
        sa.CheckConstraint(
            "provider_request_id IS NULL OR char_length(provider_request_id) BETWEEN 1 AND 128",
            name="ck_model_runs_provider_request_id_length",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_model_runs_input_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_model_runs_output_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_model_runs_total_tokens_non_negative",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR output_tokens IS NULL OR total_tokens IS NULL "
            "OR total_tokens = input_tokens + output_tokens",
            name="ck_model_runs_total_tokens_consistent",
        ),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ck_model_runs_estimated_cost_non_negative",
        ),
        sa.CheckConstraint(
            "actual_cost IS NULL OR actual_cost >= 0",
            name="ck_model_runs_actual_cost_non_negative",
        ),
        sa.CheckConstraint(
            "input_price_per_million_snapshot IS NULL OR input_price_per_million_snapshot >= 0",
            name="ck_model_runs_input_price_snapshot_non_negative",
        ),
        sa.CheckConstraint(
            "output_price_per_million_snapshot IS NULL OR output_price_per_million_snapshot >= 0",
            name="ck_model_runs_output_price_snapshot_non_negative",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_model_runs_duration_non_negative",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 64",
            name="ck_model_runs_failure_code_length",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR char_length(currency) = 3",
            name="ck_model_runs_currency_length",
        ),
        sa.CheckConstraint(
            "(estimated_cost IS NULL AND actual_cost IS NULL AND input_price_per_million_snapshot IS NULL AND output_price_per_million_snapshot IS NULL) OR currency IS NOT NULL",
            name="ck_model_runs_money_currency",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'SUCCEEDED' AND completed_at IS NOT NULL AND failure_code IS NULL) OR (status = 'FAILED' AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR (status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code = 'cancellation')",
            name="ck_model_runs_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_model_runs_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_model_runs_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_model_runs_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_model_runs_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_definition_id"],
            ["model_definitions.id"],
            name="fk_model_runs_model_definition_id_model_definitions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_runs_scope_created",
        "model_runs",
        ["tenant_id", "workspace_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the I-019 model-run accounting table."""
    op.drop_index("ix_model_runs_scope_created", table_name="model_runs")
    op.drop_table("model_runs")
