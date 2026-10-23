"""Immutable scoped specification history.

Revision ID: 20261023_0043
Revises: 20261022_0042
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261023_0043"
down_revision = "20261022_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cadrage_specifications",
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
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "editor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "conversation_id", "version", name="uq_cadrage_spec_version"
        ),
        sa.CheckConstraint("version > 0", name="ck_cadrage_spec_version"),
    )


def downgrade() -> None:
    op.drop_table("cadrage_specifications")
