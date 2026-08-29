"""Add fail-closed Memory sensitivity and model disclosure metadata.

Revision ID: 20260830_0023
Revises: 20260829_0022
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0023"
down_revision: str | None = "20260829_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve rows while making their new remote disclosure authority fail closed."""
    op.add_column(
        "memory_records",
        sa.Column(
            "sensitivity",
            sa.String(length=16),
            nullable=False,
            server_default="INTERNAL",
        ),
    )
    op.add_column(
        "memory_records",
        sa.Column(
            "model_access",
            sa.String(length=24),
            nullable=False,
            server_default="LOCAL_ONLY",
        ),
    )
    op.create_check_constraint(
        "ck_memory_records_sensitivity_value",
        "memory_records",
        "sensitivity IN ('PUBLIC', 'INTERNAL', 'SENSITIVE', 'RESTRICTED')",
    )
    op.create_check_constraint(
        "ck_memory_records_model_access_value",
        "memory_records",
        "model_access IN ('LOCAL_ONLY', 'LOCAL_AND_REMOTE')",
    )
    op.create_check_constraint(
        "ck_memory_records_restricted_local_only",
        "memory_records",
        "sensitivity != 'RESTRICTED' OR model_access = 'LOCAL_ONLY'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_memory_records_restricted_local_only", "memory_records", type_="check"
    )
    op.drop_constraint(
        "ck_memory_records_model_access_value", "memory_records", type_="check"
    )
    op.drop_constraint(
        "ck_memory_records_sensitivity_value", "memory_records", type_="check"
    )
    op.drop_column("memory_records", "model_access")
    op.drop_column("memory_records", "sensitivity")
