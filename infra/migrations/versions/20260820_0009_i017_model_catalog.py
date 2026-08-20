"""Add I-017 authoritative model catalog.

Revision ID: 20260820_0009
Revises: 20260820_0008
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0009"
down_revision: str = "20260820_0008"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create only the global normalized model definition table."""
    op.create_table(
        "model_definitions",
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("provider_model_id", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("reasoning", sa.Boolean(), nullable=True),
        sa.Column("coding", sa.Boolean(), nullable=True),
        sa.Column("tool_calling", sa.Boolean(), nullable=True),
        sa.Column("structured_output", sa.Boolean(), nullable=True),
        sa.Column("vision", sa.Boolean(), nullable=True),
        sa.Column(
            "input_price_per_million", sa.Numeric(precision=20, scale=10), nullable=True
        ),
        sa.Column(
            "output_price_per_million",
            sa.Numeric(precision=20, scale=10),
            nullable=True,
        ),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("free_allowlisted", sa.Boolean(), nullable=False),
        sa.Column("family", sa.String(length=128), nullable=True),
        sa.Column("revision", sa.String(length=128), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(provider_id) BETWEEN 1 AND 64",
            name="ck_model_definitions_provider_id_length",
        ),
        sa.CheckConstraint(
            "char_length(provider_model_id) BETWEEN 1 AND 256",
            name="ck_model_definitions_provider_model_id_length",
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 200",
            name="ck_model_definitions_display_name_length",
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE', 'UNAVAILABLE', 'STALE', 'UNKNOWN')",
            name="ck_model_definitions_status_value",
        ),
        sa.CheckConstraint(
            "context_window IS NULL OR context_window BETWEEN 1 AND 10000000",
            name="ck_model_definitions_context_window_value",
        ),
        sa.CheckConstraint(
            "input_price_per_million IS NULL OR input_price_per_million >= 0",
            name="ck_model_definitions_input_price_non_negative",
        ),
        sa.CheckConstraint(
            "output_price_per_million IS NULL OR output_price_per_million >= 0",
            name="ck_model_definitions_output_price_non_negative",
        ),
        sa.CheckConstraint(
            "((input_price_per_million IS NULL AND output_price_per_million IS NULL) "
            "AND currency IS NULL) OR ((input_price_per_million IS NOT NULL OR "
            "output_price_per_million IS NOT NULL) AND char_length(currency) = 3)",
            name="ck_model_definitions_pricing_currency",
        ),
        sa.CheckConstraint(
            "family IS NULL OR char_length(family) BETWEEN 1 AND 128",
            name="ck_model_definitions_family_length",
        ),
        sa.CheckConstraint(
            "revision IS NULL OR char_length(revision) BETWEEN 1 AND 128",
            name="ck_model_definitions_revision_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_id",
            "provider_model_id",
            name="uq_model_definitions_provider_id_provider_model_id",
        ),
    )
    op.create_index(
        "ix_model_definitions_status_provider_model",
        "model_definitions",
        ["status", "provider_id", "provider_model_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the I-017 model catalog schema."""
    op.drop_index(
        "ix_model_definitions_status_provider_model", table_name="model_definitions"
    )
    op.drop_table("model_definitions")
