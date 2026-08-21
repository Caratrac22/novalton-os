"""Add I-023 versioned workflow graphs and per-run step state.

Revision ID: 20260820_0012
Revises: 20260820_0011
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0012"
down_revision: str = "20260820_0011"
branch_labels: None = None
depends_on: None = None

UUID = postgresql.UUID(as_uuid=True)
timestamps = lambda: (
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
)


def upgrade() -> None:
    op.create_table(
        "workflow_plans",
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("change_reason", sa.String(500), nullable=True),
        *timestamps(),
        sa.CheckConstraint("version > 0", name="ck_workflow_plans_version_positive"),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name="ck_workflow_plans_title_length",
        ),
        sa.CheckConstraint(
            "summary IS NULL OR char_length(summary) <= 2000",
            name="ck_workflow_plans_summary_length",
        ),
        sa.CheckConstraint(
            "change_reason IS NULL OR char_length(change_reason) BETWEEN 1 AND 500",
            name="ck_workflow_plans_change_reason_length",
        ),
        sa.CheckConstraint(
            "(version = 1 AND change_reason IS NULL) OR (version > 1 AND change_reason IS NOT NULL)",
            name="ck_workflow_plans_change_reason_version",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "task_id",
            "version",
            name="uq_workflow_plans_scope_task_version",
        ),
    )
    op.create_index(
        "ix_workflow_plans_scope_task_created",
        "workflow_plans",
        ["tenant_id", "workspace_id", "task_id", "created_at", "id"],
    )
    op.create_table(
        "workflow_steps",
        sa.Column("workflow_plan_id", UUID, nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("step_type", sa.String(24), nullable=False),
        sa.Column("assigned_capability", sa.String(64), nullable=True),
        sa.Column("agent_definition_id", UUID, nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "step_key ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_workflow_steps_key_format"
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200",
            name="ck_workflow_steps_title_length",
        ),
        sa.CheckConstraint(
            "step_type IN ('AGENT_TASK', 'MANUAL_REVIEW', 'SYSTEM')",
            name="ck_workflow_steps_type_value",
        ),
        sa.CheckConstraint(
            "assigned_capability IS NULL OR assigned_capability ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_workflow_steps_capability_format",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_workflow_steps_position_nonnegative"
        ),
        sa.CheckConstraint(
            "risk_level IS NULL OR risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_workflow_steps_risk_value",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_plan_id"], ["workflow_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"], ["agent_definitions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_plan_id", "step_key", name="uq_workflow_steps_plan_key"
        ),
        sa.UniqueConstraint(
            "workflow_plan_id", "position", name="uq_workflow_steps_plan_position"
        ),
        sa.UniqueConstraint("id", "workflow_plan_id", name="uq_workflow_steps_id_plan"),
    )
    op.create_table(
        "workflow_step_dependencies",
        sa.Column("workflow_plan_id", UUID, nullable=False),
        sa.Column("workflow_step_id", UUID, nullable=False),
        sa.Column("depends_on_step_id", UUID, nullable=False),
        sa.CheckConstraint(
            "workflow_step_id <> depends_on_step_id",
            name="ck_workflow_step_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_plan_id"], ["workflow_plans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id", "workflow_plan_id"],
            ["workflow_steps.id", "workflow_steps.workflow_plan_id"],
            name="fk_workflow_dependencies_step_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["depends_on_step_id", "workflow_plan_id"],
            ["workflow_steps.id", "workflow_steps.workflow_plan_id"],
            name="fk_workflow_dependencies_prerequisite_plan",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workflow_plan_id", "workflow_step_id", "depends_on_step_id"
        ),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("workflow_plan_id", UUID, nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "plan_version > 0", name="ck_workflow_runs_plan_version_positive"
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_workflow_runs_status_value",
        ),
        sa.CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_workflow_runs_correlation_length",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_workflow_runs_failure_format",
        ),
        sa.CheckConstraint(
            "(status = 'CREATED' AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'COMPLETED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR (status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR (status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
            name="ck_workflow_runs_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_workflow_runs_timestamp_order",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_plan_id"], ["workflow_plans.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workflow_plan_id", name="uq_workflow_runs_id_plan"),
    )
    op.create_index(
        "ix_workflow_runs_scope_created",
        "workflow_runs",
        ["tenant_id", "workspace_id", "created_at", "id"],
    )
    op.create_table(
        "workflow_step_runs",
        sa.Column("workflow_run_id", UUID, nullable=False),
        sa.Column("workflow_plan_id", UUID, nullable=False),
        sa.Column("workflow_step_id", UUID, nullable=False),
        sa.Column("agent_run_id", UUID, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('PENDING', 'READY', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="ck_workflow_step_runs_status_value",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_workflow_step_runs_failure_format",
        ),
        sa.CheckConstraint(
            "(status IN ('PENDING', 'READY') AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'COMPLETED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR (status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR (status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
            name="ck_workflow_step_runs_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_workflow_step_runs_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "workflow_plan_id"],
            ["workflow_runs.id", "workflow_runs.workflow_plan_id"],
            name="fk_workflow_step_runs_run_plan",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_step_id", "workflow_plan_id"],
            ["workflow_steps.id", "workflow_steps.workflow_plan_id"],
            name="fk_workflow_step_runs_step_plan",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id", "workflow_step_id", name="uq_workflow_step_runs_run_step"
        ),
        sa.UniqueConstraint("agent_run_id"),
    )
    op.create_index(
        "ix_workflow_step_runs_run_status",
        "workflow_step_runs",
        ["workflow_run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_step_runs_run_status", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")
    op.drop_index("ix_workflow_runs_scope_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_step_dependencies")
    op.drop_table("workflow_steps")
    op.drop_index("ix_workflow_plans_scope_task_created", table_name="workflow_plans")
    op.drop_table("workflow_plans")
