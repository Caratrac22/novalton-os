"""Bind controlled dispatch decisions to revocable human/workspace permissions."""

from alembic import op
from sqlalchemy import text

revision = "20261021_0035"
down_revision = "20261020_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE human_operators (
            id uuid PRIMARY KEY, label varchar(128) NOT NULL,
            active boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_human_operator_label CHECK (char_length(label) BETWEEN 1 AND 128)
        )
    """)
    op.execute("""
        CREATE TABLE workspace_operator_permissions (
            user_id uuid NOT NULL REFERENCES human_operators(id) ON DELETE RESTRICT,
            tenant_id uuid NOT NULL, workspace_id uuid NOT NULL,
            permission varchar(32) NOT NULL, active boolean NOT NULL,
            revoked_at timestamptz,
            PRIMARY KEY (user_id, tenant_id, workspace_id, permission),
            CONSTRAINT fk_operator_permission_workspace_scope
                FOREIGN KEY (workspace_id, tenant_id)
                REFERENCES workspaces (id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT ck_operator_permission_name CHECK
                (permission IN ('activation.configure','dispatch.enqueue','dispatch.read',
                'dispatch.cancel','dispatch.resolve')),
            CONSTRAINT ck_operator_permission_revocation CHECK
                ((active AND revoked_at IS NULL) OR (NOT active AND revoked_at IS NOT NULL))
        )
    """)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(text("SELECT EXISTS (SELECT 1 FROM human_operators)")):
        raise RuntimeError("operator_identity_downgrade_has_history")
    op.drop_table("workspace_operator_permissions")
    op.drop_table("human_operators")
