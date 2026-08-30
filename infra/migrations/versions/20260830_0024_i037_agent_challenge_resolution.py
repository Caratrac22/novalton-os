"""Add durable trusted-human Agent challenge resolution.

Revision ID: 20260830_0024
Revises: 20260830_0023
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0024"
down_revision: str | None = "20260830_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_challenge_resolutions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_step_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("challenge_level", sa.String(length=32), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=False),
        sa.Column("specialization_role", sa.String(length=24), nullable=True),
        sa.Column("qa_verdict", sa.String(length=24), nullable=True),
        sa.Column("decision", sa.String(length=24), nullable=True),
        sa.Column("decision_actor_type", sa.String(length=16), nullable=True),
        sa.Column("decision_actor_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "challenge_level IN ('HUMAN_REVIEW_RECOMMENDED', 'BLOCK_RECOMMENDED')",
            name="ck_agent_challenge_resolutions_level",
        ),
        sa.CheckConstraint(
            "result_status IN ('COMPLETED', 'PARTIAL')",
            name="ck_agent_challenge_resolutions_result_status",
        ),
        sa.CheckConstraint(
            "specialization_role IS NULL OR specialization_role IN "
            "('developer_manager', 'developer_worker', 'qa_worker')",
            name="ck_agent_challenge_resolutions_role",
        ),
        sa.CheckConstraint(
            "qa_verdict IS NULL OR qa_verdict IN "
            "('PASS', 'PASS_WITH_WARNINGS', 'FAIL', 'INCONCLUSIVE')",
            name="ck_agent_challenge_resolutions_qa_verdict",
        ),
        sa.CheckConstraint(
            "(specialization_role = 'qa_worker' AND qa_verdict IS NOT NULL) OR "
            "(specialization_role IS DISTINCT FROM 'qa_worker' AND qa_verdict IS NULL)",
            name="ck_agent_challenge_resolutions_qa_role_verdict",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('ACCEPT_RESULT', 'REJECT_RESULT')",
            name="ck_agent_challenge_resolutions_decision",
        ),
        sa.CheckConstraint(
            "challenge_level != 'BLOCK_RECOMMENDED' OR decision IS NULL "
            "OR decision = 'REJECT_RESULT'",
            name="ck_agent_challenge_resolutions_block_decision",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) BETWEEN 1 AND 500",
            name="ck_agent_challenge_resolutions_reason",
        ),
        sa.CheckConstraint(
            "(decision IS NULL AND decision_actor_type IS NULL AND decision_actor_id IS NULL "
            "AND reason IS NULL AND decided_at IS NULL) OR "
            "(decision IS NOT NULL AND decision_actor_type = 'local_user' "
            "AND decision_actor_id IS NULL AND decided_at IS NOT NULL)",
            name="ck_agent_challenge_resolutions_decision_state",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_run_id"], ["workflow_step_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_step_run_id", name="uq_agent_challenge_resolutions_step_run"
        ),
        sa.UniqueConstraint(
            "agent_run_id", name="uq_agent_challenge_resolutions_agent_run"
        ),
    )
    op.create_index(
        "ix_agent_challenge_resolutions_scope_created",
        "agent_challenge_resolutions",
        ["tenant_id", "workspace_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_challenge_resolutions_scope_created",
        table_name="agent_challenge_resolutions",
    )
    op.drop_table("agent_challenge_resolutions")
