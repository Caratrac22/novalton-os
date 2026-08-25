"""Persist normalized model completion-token limits for I-047.

Revision ID: 20260825_0015
Revises: 20260825_0014
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0015"
down_revision: str = "20260825_0014"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("model_definitions", sa.Column("max_output_tokens", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_model_definitions_max_output_tokens_value",
        "model_definitions",
        "max_output_tokens IS NULL OR max_output_tokens BETWEEN 1 AND 65536",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_model_definitions_max_output_tokens_value", "model_definitions", type_="check"
    )
    op.drop_column("model_definitions", "max_output_tokens")
