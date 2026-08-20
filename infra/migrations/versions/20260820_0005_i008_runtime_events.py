"""Add I-008 append-only runtime events.

Revision ID: 20260820_0005
Revises: 20260820_0004
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0005"
down_revision: str = "20260820_0004"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the scoped append-only runtime event table."""
    op.create_table(
        "runtime_events",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_runtime_events_correlation_id_length",
        ),
        sa.CheckConstraint(
            "char_length(event_type) BETWEEN 3 AND 100",
            name="ck_runtime_events_event_type_length",
        ),
        sa.CheckConstraint(
            "char_length(source) BETWEEN 1 AND 64",
            name="ck_runtime_events_source_length",
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_runtime_events_task_requires_project",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_runtime_events_project_id_projects",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_runtime_events_task_id_tasks",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_runtime_events_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_runtime_events_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_events_scope_occurred_at_id",
        "runtime_events",
        ["tenant_id", "workspace_id", "occurred_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the I-008 runtime event table."""
    op.drop_index("ix_runtime_events_scope_occurred_at_id", table_name="runtime_events")
    op.drop_table("runtime_events")
