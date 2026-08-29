"""Add authoritative execution-target classification to catalog models.

Revision ID: 20260829_0022
Revises: 20260827_0021
Create Date: 2026-08-29
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0022"
down_revision: str | None = "20260827_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Classify legacy targets conservatively as REMOTE without rewriting data."""
    op.add_column(
        "model_definitions",
        sa.Column(
            "execution_target_class",
            sa.String(length=16),
            nullable=False,
            server_default="REMOTE",
        ),
    )
    op.create_check_constraint(
        "ck_model_definitions_execution_target_class_value",
        "model_definitions",
        "execution_target_class IN ('LOCAL', 'REMOTE')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_definitions_execution_target_class_value",
        "model_definitions",
        type_="check",
    )
    op.drop_column("model_definitions", "execution_target_class")
