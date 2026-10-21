"""Require tenant membership in addition to exact workspace grants."""

from alembic import op
from sqlalchemy import text

revision = "20261021_0036"
down_revision = "20261021_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE tenant_operator_memberships (
            user_id uuid NOT NULL REFERENCES human_operators(id) ON DELETE RESTRICT,
            tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
            role varchar(16) NOT NULL, active boolean NOT NULL,
            revoked_at timestamptz,
            PRIMARY KEY (user_id, tenant_id),
            CONSTRAINT ck_operator_membership_role
                CHECK (role IN ('OWNER','ADMIN','MEMBER','VIEWER')),
            CONSTRAINT ck_operator_membership_revocation
                CHECK ((active AND revoked_at IS NULL)
                    OR (NOT active AND revoked_at IS NOT NULL))
        )
    """)
    # Preserve existing legitimate scoped operators without granting any new workspace.
    op.execute("""
        INSERT INTO tenant_operator_memberships (user_id, tenant_id, role, active, revoked_at)
        SELECT user_id, tenant_id, 'MEMBER', bool_or(active),
               CASE WHEN bool_or(active) THEN NULL ELSE now() END
        FROM workspace_operator_permissions GROUP BY user_id, tenant_id
    """)


def downgrade() -> None:
    if op.get_bind().scalar(
        text("SELECT EXISTS (SELECT 1 FROM tenant_operator_memberships)")
    ):
        raise RuntimeError("operator_membership_downgrade_has_history")
    op.drop_table("tenant_operator_memberships")
