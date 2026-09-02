"""Bind approvals to prepared workspace mutations."""

import sqlalchemy as sa
from alembic import op

revision = "20260831_0026"
down_revision = "20260831_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_calls", sa.Column("mutation_fingerprint", sa.String(64), nullable=True)
    )
    op.add_column(
        "tool_calls", sa.Column("preimage_sha256", sa.String(64), nullable=True)
    )
    op.add_column(
        "tool_calls", sa.Column("candidate_sha256", sa.String(64), nullable=True)
    )
    op.add_column(
        "tool_calls", sa.Column("prepared_mutation", sa.JSON(), nullable=True)
    )
    op.drop_constraint("ck_tool_calls_read_only", "tool_calls", type_="check")
    op.create_check_constraint(
        "ck_tool_calls_side_effect",
        "tool_calls",
        "side_effect_class IN ('READ_ONLY','MUTATION')",
    )
    op.add_column(
        "approval_requests",
        sa.Column("mutation_fingerprint", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approval_requests", "mutation_fingerprint")
    op.drop_constraint("ck_tool_calls_side_effect", "tool_calls", type_="check")
    op.create_check_constraint(
        "ck_tool_calls_read_only", "tool_calls", "side_effect_class = 'READ_ONLY'"
    )
    op.drop_column("tool_calls", "prepared_mutation")
    op.drop_column("tool_calls", "candidate_sha256")
    op.drop_column("tool_calls", "preimage_sha256")
    op.drop_column("tool_calls", "mutation_fingerprint")
