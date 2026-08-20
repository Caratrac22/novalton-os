"""Add I-007 project-scoped tasks.

Revision ID: 20260820_0004
Revises: 20260820_0003
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0004"
down_revision: str = "20260820_0003"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the project-scoped tasks table."""
    op.create_table(
        "tasks",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
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
            name="ck_tasks_description_length",
        ),
        sa.CheckConstraint(
            "status IN ('BACKLOG', 'READY', 'IN_PROGRESS', 'BLOCKED', 'REVIEW', "
            "'DONE', 'CANCELLED')",
            name="ck_tasks_status_value",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 200", name="ck_tasks_title_length"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_tasks_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Remove the I-007 tasks table."""
    op.drop_table("tasks")
