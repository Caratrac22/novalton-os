"""Persist scoped, non-executing plan compilation proposals.

Revision ID: 20261024_0046
Revises: 20261023_0045
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261024_0046"
down_revision = "20261023_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cadrage_compilations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "plan_id", "task_id", name="uq_cadrage_compilation_plan_task"
        ),
        sa.CheckConstraint(
            "status IN ('BLOCKED','PROPOSED')", name="ck_cadrage_compilation_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("cadrage_compilations")
