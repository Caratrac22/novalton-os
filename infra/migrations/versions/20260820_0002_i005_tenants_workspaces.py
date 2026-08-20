"""Add I-005 tenant and workspace foundations.

Revision ID: 20260820_0002
Revises: 20260820_0001
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0002"
down_revision: str = "20260820_0001"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the tenant and tenant-scoped workspace tables."""
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
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
            "char_length(name) BETWEEN 1 AND 200", name="ck_tenants_name_length"
        ),
        sa.CheckConstraint(
            "char_length(slug) BETWEEN 1 AND 63", name="ck_tenants_slug_length"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_table(
        "workspaces",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
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
            "char_length(name) BETWEEN 1 AND 200", name="ck_workspaces_name_length"
        ),
        sa.CheckConstraint(
            "char_length(slug) BETWEEN 1 AND 63", name="ck_workspaces_slug_length"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_workspaces_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_id_slug"),
    )


def downgrade() -> None:
    """Remove I-005 tables in dependency order."""
    op.drop_table("workspaces")
    op.drop_table("tenants")
