"""Add durable trusted tool call metadata.

Revision ID: 20260831_0025
Revises: 20260830_0024
Create Date: 2026-08-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0025"
down_revision: str = "20260830_0024"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_model_runs_recovery_attempt_kind", "model_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_model_runs_recovery_attempt_kind",
        "model_runs",
        "recovery_attempt_kind IN ('INITIAL', 'TRUNCATION', 'CONTRACT_REPAIR', 'TOOL_CONTINUATION')",
    )
    op.create_table(
        "tool_calls",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "proposal_model_run_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("call_key", sa.String(100), nullable=False),
        sa.Column("tool_id", sa.String(100), nullable=False),
        sa.Column("safe_input_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("policy_effect", sa.String(24), nullable=True),
        sa.Column("matched_rule_ids", postgresql.JSONB(), nullable=False),
        sa.Column("execution_target_class", sa.String(16), nullable=False),
        sa.Column("side_effect_class", sa.String(16), nullable=False),
        sa.Column("result_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
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
            "char_length(tool_id) BETWEEN 1 AND 100",
            name="ck_tool_calls_tool_id_length",
        ),
        sa.CheckConstraint(
            "char_length(call_key) BETWEEN 1 AND 100",
            name="ck_tool_calls_call_key_length",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED','PENDING_APPROVAL','RUNNING','SUCCEEDED','FAILED','BLOCKED')",
            name="ck_tool_calls_status_value",
        ),
        sa.CheckConstraint(
            "policy_effect IS NULL OR policy_effect IN ('ALLOW','ALLOW_WITH_LOG','REQUIRE_CONFIRMATION','BLOCK')",
            name="ck_tool_calls_policy_effect_value",
        ),
        sa.CheckConstraint(
            "execution_target_class = 'LOCAL'", name="ck_tool_calls_target_local"
        ),
        sa.CheckConstraint(
            "side_effect_class = 'READ_ONLY'", name="ck_tool_calls_read_only"
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 64",
            name="ck_tool_calls_failure_code_length",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_tool_calls_timestamp_order",
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_tool_calls_task_requires_project",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(safe_input_metadata) = 'object'",
            name="ck_tool_calls_safe_input_shape",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matched_rule_ids) = 'array' AND jsonb_array_length(matched_rule_ids) <= 64",
            name="ck_tool_calls_matched_rules_shape",
        ),
        sa.CheckConstraint(
            "result_metadata IS NULL OR jsonb_typeof(result_metadata) = 'object'",
            name="ck_tool_calls_result_shape",
        ),
        sa.CheckConstraint(
            "(status IN ('PROPOSED','PENDING_APPROVAL') AND started_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status IN ('SUCCEEDED','FAILED') AND started_at IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status = 'BLOCKED' AND completed_at IS NOT NULL)",
            name="ck_tool_calls_lifecycle_shape",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_model_run_id"], ["model_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id"], ["approval_requests.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_run_id", "call_key", name="uq_tool_calls_agent_run_call_key"
        ),
    )
    op.create_index(
        "ix_tool_calls_scope_created",
        "tool_calls",
        ["tenant_id", "workspace_id", "created_at", "id"],
    )
    op.create_index(
        "ix_tool_calls_agent_created",
        "tool_calls",
        ["agent_run_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_calls_agent_created", table_name="tool_calls")
    op.drop_index("ix_tool_calls_scope_created", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_constraint(
        "ck_model_runs_recovery_attempt_kind", "model_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_model_runs_recovery_attempt_kind",
        "model_runs",
        "recovery_attempt_kind IN ('INITIAL', 'TRUNCATION', 'CONTRACT_REPAIR')",
    )
