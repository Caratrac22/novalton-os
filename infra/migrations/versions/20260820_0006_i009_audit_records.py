"""Add I-009 append-only audit records.

Revision ID: 20260820_0006
Revises: 20260820_0005
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0006"
down_revision: str = "20260820_0005"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the scoped append-only audit record table."""
    op.create_table(
        "audit_records",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(action) BETWEEN 3 AND 100", name="ck_audit_records_action_length"
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'api', 'local_user', 'service')",
            name="ck_audit_records_actor_type_value",
        ),
        sa.CheckConstraint(
            "actor_id IS NULL OR char_length(actor_id) BETWEEN 1 AND 128",
            name="ck_audit_records_actor_id_length",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure', 'blocked', 'cancelled')",
            name="ck_audit_records_outcome_value",
        ),
        sa.CheckConstraint(
            "resource_type IS NULL OR resource_type IN ('project', 'task')",
            name="ck_audit_records_resource_type_value",
        ),
        sa.CheckConstraint(
            "(resource_type IS NULL) = (resource_id IS NULL)",
            name="ck_audit_records_resource_pair",
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_audit_records_task_requires_project",
        ),
        sa.CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_audit_records_correlation_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_audit_records_project_id_projects", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_audit_records_task_id_tasks", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_audit_records_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_audit_records_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_records_scope_occurred_at_id",
        "audit_records",
        ["tenant_id", "workspace_id", "occurred_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the I-009 audit record table."""
    op.drop_index("ix_audit_records_scope_occurred_at_id", table_name="audit_records")
    op.drop_table("audit_records")
