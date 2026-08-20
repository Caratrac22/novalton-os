"""Add I-013 deterministic policy rules.

Revision ID: 20260820_0007
Revises: 20260820_0006
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0007"
down_revision: str = "20260820_0006"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create the tenant-owned, optionally workspace-scoped policy table."""
    op.create_table(
        "policy_rules",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("action_pattern", sa.String(length=100), nullable=False),
        sa.Column("effect", sa.String(length=24), nullable=False),
        sa.Column("actor_type", sa.String(length=64), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column(
            "conditions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
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
            "char_length(name) BETWEEN 1 AND 200", name="ck_policy_rules_name_length"
        ),
        sa.CheckConstraint(
            "char_length(action_pattern) BETWEEN 1 AND 100",
            name="ck_policy_rules_action_pattern_length",
        ),
        sa.CheckConstraint(
            "effect IN ('ALLOW', 'ALLOW_WITH_LOG', 'REQUIRE_CONFIRMATION', 'BLOCK')",
            name="ck_policy_rules_effect_value",
        ),
        sa.CheckConstraint(
            "actor_type IS NULL OR char_length(actor_type) BETWEEN 1 AND 64",
            name="ck_policy_rules_actor_type_length",
        ),
        sa.CheckConstraint(
            "resource_type IS NULL OR char_length(resource_type) BETWEEN 1 AND 64",
            name="ck_policy_rules_resource_type_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_policy_rules_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_policy_rules_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_policy_rules_scope_enabled_action",
        "policy_rules",
        ["tenant_id", "workspace_id", "enabled", "action_pattern"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the I-013 policy table."""
    op.drop_index("ix_policy_rules_scope_enabled_action", table_name="policy_rules")
    op.drop_table("policy_rules")
