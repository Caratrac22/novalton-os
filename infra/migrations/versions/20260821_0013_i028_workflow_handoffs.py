"""Add typed durable handoffs for the first vertical workflow.

Revision ID: 20260821_0013
Revises: 20260820_0012
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0013"
down_revision: str = "20260820_0012"
branch_labels: None = None
depends_on: None = None
UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_workflow_step_runs_id_run_plan",
        "workflow_step_runs",
        ["id", "workflow_run_id", "workflow_plan_id"],
    )
    op.create_table(
        "workflow_step_handoffs",
        sa.Column("workflow_run_id", UUID, nullable=False),
        sa.Column("workflow_plan_id", UUID, nullable=False),
        sa.Column("source_step_run_id", UUID, nullable=True),
        sa.Column("destination_step_run_id", UUID, nullable=False),
        sa.Column("handoff_type", sa.String(32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column(
            "acceptance_criteria", postgresql.ARRAY(sa.String(1000)), nullable=False
        ),
        sa.Column("evidence_items", postgresql.ARRAY(sa.String(1000)), nullable=False),
        sa.Column("id", UUID, nullable=False),
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
            "handoff_type IN ('DEVELOPMENT_REQUEST', 'MANAGER_ASSIGNMENT', 'WORKER_EVIDENCE')",
            name="ck_workflow_handoffs_type",
        ),
        sa.CheckConstraint(
            "char_length(objective) BETWEEN 1 AND 2000",
            name="ck_workflow_handoffs_objective",
        ),
        sa.CheckConstraint(
            "cardinality(acceptance_criteria) BETWEEN 1 AND 24",
            name="ck_workflow_handoffs_criteria",
        ),
        sa.CheckConstraint(
            "cardinality(evidence_items) <= 64", name="ck_workflow_handoffs_evidence"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "workflow_plan_id"],
            ["workflow_runs.id", "workflow_runs.workflow_plan_id"],
            name="fk_workflow_handoffs_run_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_step_run_id", "workflow_run_id", "workflow_plan_id"],
            [
                "workflow_step_runs.id",
                "workflow_step_runs.workflow_run_id",
                "workflow_step_runs.workflow_plan_id",
            ],
            name="fk_workflow_handoffs_destination_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_step_run_id", "workflow_run_id", "workflow_plan_id"],
            [
                "workflow_step_runs.id",
                "workflow_step_runs.workflow_run_id",
                "workflow_step_runs.workflow_plan_id",
            ],
            name="fk_workflow_handoffs_source_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "destination_step_run_id", name="uq_workflow_handoffs_destination"
        ),
        sa.UniqueConstraint("source_step_run_id", name="uq_workflow_handoffs_source"),
    )


def downgrade() -> None:
    op.drop_table("workflow_step_handoffs")
    op.drop_constraint(
        "uq_workflow_step_runs_id_run_plan", "workflow_step_runs", type_="unique"
    )
