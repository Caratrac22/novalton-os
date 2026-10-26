"""Bind one authorized compilation to one created workflow atomically.

Revision ID: 20261026_0049
Revises: 20261026_0048
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261026_0049"
down_revision = "20261026_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "launch_authorizations",
        sa.Column("workflow_plan_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "launch_authorizations",
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "launch_authorizations",
        sa.Column("launch_request_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "launch_authorizations", sa.Column("dispatch_generation", sa.Integer())
    )
    op.create_foreign_key(
        "fk_launch_workflow_plan",
        "launch_authorizations",
        "workflow_plans",
        ["workflow_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_launch_workflow_run",
        "launch_authorizations",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_launch_workflow_run", "launch_authorizations", ["workflow_run_id"]
    )
    op.create_index(
        "uq_launch_compilation_workflow",
        "launch_authorizations",
        ["compilation_id"],
        unique=True,
        postgresql_where=sa.text("workflow_run_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_launch_workflow_binding_complete",
        "launch_authorizations",
        "(workflow_plan_id IS NULL AND workflow_run_id IS NULL AND "
        "launch_request_id IS NULL AND dispatch_generation IS NULL) OR "
        "(workflow_plan_id IS NOT NULL AND workflow_run_id IS NOT NULL AND "
        "launch_request_id IS NOT NULL AND dispatch_generation > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_launch_workflow_binding_complete", "launch_authorizations", type_="check"
    )
    op.drop_index("uq_launch_compilation_workflow", table_name="launch_authorizations")
    op.drop_constraint(
        "uq_launch_workflow_run", "launch_authorizations", type_="unique"
    )
    op.drop_constraint(
        "fk_launch_workflow_run", "launch_authorizations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_launch_workflow_plan", "launch_authorizations", type_="foreignkey"
    )
    op.drop_column("launch_authorizations", "dispatch_generation")
    op.drop_column("launch_authorizations", "launch_request_id")
    op.drop_column("launch_authorizations", "workflow_run_id")
    op.drop_column("launch_authorizations", "workflow_plan_id")
