"""Versioned plan and human decision; no workflow trigger.

Revision ID: 20261023_0045
Revises: 20261023_0044
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261023_0045"
down_revision = "20261023_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cadrage_plans",
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
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "specification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_specifications.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "decided_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("specification_id", name="uq_cadrage_plan_specification"),
        sa.CheckConstraint(
            "status IN ('DRAFT','READY_FOR_REVIEW','APPROVED','REJECTED','NEEDS_CHANGES','SUPERSEDED')",
            name="ck_cadrage_plan_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("cadrage_plans")
