"""Add per-agent model attempt linkage and resolved provider identity.

Revision ID: 20260825_0014
Revises: 20260821_0013
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0014"
down_revision: str = "20260821_0013"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "model_runs",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "model_runs",
        sa.Column("provider_resolved_model_id", sa.String(256), nullable=True),
    )
    op.create_check_constraint(
        "ck_model_runs_provider_resolved_model_id_length",
        "model_runs",
        "provider_resolved_model_id IS NULL OR char_length(provider_resolved_model_id) BETWEEN 1 AND 256",
    )
    op.create_foreign_key(
        "fk_model_runs_agent_run_id_agent_runs",
        "model_runs",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_model_runs_agent_run_created",
        "model_runs",
        ["agent_run_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_runs_agent_run_created", table_name="model_runs")
    op.drop_constraint(
        "fk_model_runs_agent_run_id_agent_runs", "model_runs", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_model_runs_provider_resolved_model_id_length", "model_runs", type_="check"
    )
    op.drop_column("model_runs", "provider_resolved_model_id")
    op.drop_column("model_runs", "agent_run_id")
