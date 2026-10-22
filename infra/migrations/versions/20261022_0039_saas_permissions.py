"""Explicit workspace grants for authenticated SaaS routes."""

from alembic import op
from sqlalchemy import text

revision = "20261022_0039"
down_revision = "20261021_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_operator_permission_name", "workspace_operator_permissions", type_="check"
    )
    op.create_check_constraint(
        "ck_operator_permission_name",
        "workspace_operator_permissions",
        "permission IN ('activation.configure','dispatch.enqueue','dispatch.read',"
        "'dispatch.cancel','dispatch.resolve','workspace.read','workspace.write')",
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM workspace_operator_permissions WHERE permission IN ('workspace.read','workspace.write'))"
        )
    ):
        raise RuntimeError("saas_permissions_downgrade_has_grants")
    op.drop_constraint(
        "ck_operator_permission_name", "workspace_operator_permissions", type_="check"
    )
    op.create_check_constraint(
        "ck_operator_permission_name",
        "workspace_operator_permissions",
        "permission IN ('activation.configure','dispatch.enqueue','dispatch.read',"
        "'dispatch.cancel','dispatch.resolve')",
    )
