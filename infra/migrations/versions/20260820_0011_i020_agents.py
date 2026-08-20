"""Add I-020 versioned agent definitions and scoped runs.

Revision ID: 20260820_0011
Revises: 20260820_0010
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0011"
down_revision: str = "20260820_0010"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("mission", sa.Text(), nullable=False),
        sa.Column("capabilities", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.String(64)), nullable=False),
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
            "char_length(name) BETWEEN 1 AND 120",
            name="ck_agent_definitions_name_length",
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_agent_definitions_slug_format"
        ),
        sa.CheckConstraint("version > 0", name="ck_agent_definitions_version_positive"),
        sa.CheckConstraint(
            "status IN ('ENABLED', 'DISABLED', 'ARCHIVED')",
            name="ck_agent_definitions_status_value",
        ),
        sa.CheckConstraint(
            "category IS NULL OR char_length(category) BETWEEN 1 AND 64",
            name="ck_agent_definitions_category_length",
        ),
        sa.CheckConstraint(
            "char_length(mission) BETWEEN 1 AND 2000",
            name="ck_agent_definitions_mission_length",
        ),
        sa.CheckConstraint(
            "cardinality(capabilities) <= 32",
            name="ck_agent_definitions_capabilities_count",
        ),
        sa.CheckConstraint(
            "cardinality(permissions) <= 32",
            name="ck_agent_definitions_permissions_count",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "slug",
            "version",
            name="uq_agent_definitions_scope_slug_version",
        ),
    )
    op.create_index(
        "ix_agent_definitions_scope_created",
        "agent_definitions",
        ["tenant_id", "workspace_id", "created_at", "id"],
    )
    op.create_table(
        "agent_runs",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(120), nullable=False),
        sa.Column("agent_slug", sa.String(64), nullable=False),
        sa.Column("model_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=True),
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
        sa.CheckConstraint("agent_version > 0", name="ck_agent_runs_version_positive"),
        sa.CheckConstraint(
            "char_length(agent_name) BETWEEN 1 AND 120",
            name="ck_agent_runs_name_length",
        ),
        sa.CheckConstraint(
            "agent_slug ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_agent_runs_slug_format"
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_agent_runs_status_value",
        ),
        sa.CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_agent_runs_correlation_id_length",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_agent_runs_failure_code_format",
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_agent_runs_task_requires_project",
        ),
        sa.CheckConstraint(
            "parent_agent_run_id IS NULL OR parent_agent_run_id <> id",
            name="ck_agent_runs_parent_not_self",
        ),
        sa.CheckConstraint(
            "(status = 'CREATED' AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR (status = 'SUCCEEDED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR (status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR (status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
            name="ck_agent_runs_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_agent_runs_timestamp_order",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_definition_id"], ["agent_definitions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"], ["model_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_agent_run_id"], ["agent_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_run_id"),
    )
    op.create_index(
        "ix_agent_runs_scope_created",
        "agent_runs",
        ["tenant_id", "workspace_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_scope_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_definitions_scope_created", table_name="agent_definitions")
    op.drop_table("agent_definitions")
