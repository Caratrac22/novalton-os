"""Scoped, revocable human financial authorization and reservations.

Revision ID: 20261025_0047
Revises: 20261024_0046
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261025_0047"
down_revision = "20261024_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_authorizations",
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
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_limit", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("token_limit", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_limit", sa.Numeric(20, 10), nullable=False),
        sa.Column("reserved_estimate", sa.Numeric(20, 10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT",
            name="fk_financial_project_scope",
        ),
        sa.CheckConstraint("version > 0", name="ck_financial_version"),
        sa.CheckConstraint(
            "request_limit > 0 AND request_count >= 0 AND request_count <= request_limit",
            name="ck_financial_requests",
        ),
        sa.CheckConstraint(
            "token_limit > 0 AND reserved_tokens >= 0 AND reserved_tokens <= token_limit",
            name="ck_financial_tokens",
        ),
        sa.CheckConstraint(
            "estimated_limit >= 0 AND reserved_estimate >= 0 AND reserved_estimate <= estimated_limit",
            name="ck_financial_estimate",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_financial_expiry"),
        sa.CheckConstraint(
            "char_length(provider_id) BETWEEN 1 AND 64 AND char_length(model_id) BETWEEN 1 AND 256",
            name="ck_financial_model",
        ),
        sa.CheckConstraint("currency = 'USD'", name="ck_financial_currency"),
    )
    op.create_index(
        "ix_financial_scope",
        "financial_authorizations",
        ["owner_id", "tenant_id", "workspace_id", "project_id"],
    )
    op.create_table(
        "financial_reservations",
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
            "authorization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_authorizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("estimate", sa.Numeric(20, 10), nullable=False),
        sa.UniqueConstraint(
            "authorization_id", "request_id", name="uq_financial_reservation_request"
        ),
        sa.CheckConstraint(
            "tokens > 0 AND estimate >= 0", name="ck_financial_reservation_amount"
        ),
    )


def downgrade() -> None:
    op.drop_table("financial_reservations")
    op.drop_index("ix_financial_scope", table_name="financial_authorizations")
    op.drop_table("financial_authorizations")
