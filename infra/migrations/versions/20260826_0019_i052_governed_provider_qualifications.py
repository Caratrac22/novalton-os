"""Persist bounded governed-provider qualification and upstream identity facts for I-052.

Revision ID: 20260826_0019
Revises: 20260826_0018
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0019"
down_revision: str | None = "20260826_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column(
            "qualification_present",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("qualification_source", sa.String(64), nullable=True),
        sa.Column("upstream_provider_constraint", sa.String(128), nullable=True),
        sa.Column("provider_allow_fallbacks", sa.Boolean(), nullable=True),
        sa.Column(
            "provider_require_parameters",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("upstream_provider_id", sa.String(128), nullable=True),
    ):
        op.add_column("model_runs", column)
    op.create_check_constraint(
        "ck_model_runs_qualification_source_length",
        "model_runs",
        "qualification_source IS NULL OR char_length(qualification_source) BETWEEN 1 AND 64",
    )
    op.create_check_constraint(
        "ck_model_runs_upstream_provider_constraint_length",
        "model_runs",
        "upstream_provider_constraint IS NULL OR "
        "char_length(upstream_provider_constraint) BETWEEN 1 AND 128",
    )
    op.create_check_constraint(
        "ck_model_runs_upstream_provider_id_length",
        "model_runs",
        "upstream_provider_id IS NULL OR char_length(upstream_provider_id) BETWEEN 1 AND 128",
    )


def downgrade() -> None:
    for name in (
        "ck_model_runs_upstream_provider_id_length",
        "ck_model_runs_upstream_provider_constraint_length",
        "ck_model_runs_qualification_source_length",
    ):
        op.execute(f"ALTER TABLE model_runs DROP CONSTRAINT IF EXISTS {name}")
    for column in (
        "upstream_provider_id",
        "provider_require_parameters",
        "provider_allow_fallbacks",
        "upstream_provider_constraint",
        "qualification_source",
        "qualification_present",
    ):
        op.drop_column("model_runs", column)
