"""Add I-006 workspace-scoped projects.

Revision ID: 20260820_0003
Revises: 20260820_0002
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0003"
down_revision: str = "20260820_0002"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the workspace-scoped projects table."""
    op.create_table(
        "projects",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            "description IS NULL OR char_length(description) <= 4000",
            name="ck_projects_description_length",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200", name="ck_projects_name_length"
        ),
        sa.CheckConstraint(
            "char_length(slug) BETWEEN 1 AND 63", name="ck_projects_slug_length"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'PAUSED', 'ARCHIVED')",
            name="ck_projects_status_value",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_projects_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_id_slug"),
    )


def downgrade() -> None:
    """Remove the I-006 projects table."""
    op.drop_table("projects")
