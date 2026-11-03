"""Durable logical identity and context digest for financially reserved attempts.

Revision ID: 20261103_0050
Revises: 20261026_0049
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261103_0050"
down_revision = "20261026_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_reservations",
        sa.Column("logical_work_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("financial_reservations", sa.Column("attempt_kind", sa.String(32)))
    op.add_column("financial_reservations", sa.Column("attempt_index", sa.Integer()))
    op.add_column("financial_reservations", sa.Column("context_sha256", sa.String(64)))
    op.create_check_constraint(
        "ck_financial_reservation_identity_shape",
        "financial_reservations",
        "(logical_work_id IS NULL AND attempt_kind IS NULL AND attempt_index IS NULL "
        "AND context_sha256 IS NULL) OR (logical_work_id IS NOT NULL AND "
        "attempt_kind IS NOT NULL AND attempt_index IS NOT NULL AND "
        "context_sha256 IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_financial_reservation_context_hash",
        "financial_reservations",
        "context_sha256 IS NULL OR context_sha256 ~ '^[a-f0-9]{64}$'",
    )
    op.create_index(
        "uq_financial_logical_attempt",
        "financial_reservations",
        ["logical_work_id", "attempt_kind", "attempt_index"],
        unique=True,
        postgresql_where=sa.text("logical_work_id IS NOT NULL"),
    )
    op.create_index(
        "uq_financial_model_request",
        "financial_reservations",
        ["request_id"],
        unique=True,
        postgresql_where=sa.text("logical_work_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_financial_model_request", table_name="financial_reservations")
    op.drop_index("uq_financial_logical_attempt", table_name="financial_reservations")
    op.drop_constraint(
        "ck_financial_reservation_context_hash", "financial_reservations", type_="check"
    )
    op.drop_constraint(
        "ck_financial_reservation_identity_shape",
        "financial_reservations",
        type_="check",
    )
    op.drop_column("financial_reservations", "context_sha256")
    op.drop_column("financial_reservations", "attempt_index")
    op.drop_column("financial_reservations", "attempt_kind")
    op.drop_column("financial_reservations", "logical_work_id")
