"""Bind dispatch step evidence to its exact workflow at the database boundary."""

from alembic import op

revision = "20261020_0034"
down_revision = "20261020_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_workflow_step_runs_dispatch_scope", "workflow_step_runs",
        ["id", "workflow_run_id"],
    )
    op.drop_constraint(
        "dispatch_attempts_workflow_step_run_id_fkey", "dispatch_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_dispatch_attempt_step_scope", "dispatch_attempts", "workflow_step_runs",
        ["workflow_step_run_id", "workflow_run_id"], ["id", "workflow_run_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_dispatch_attempt_step_scope", "dispatch_attempts", type_="foreignkey"
    )
    op.create_foreign_key(
        "dispatch_attempts_workflow_step_run_id_fkey",
        "dispatch_attempts", "workflow_step_runs",
        ["workflow_step_run_id"], ["id"], ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_workflow_step_runs_dispatch_scope", "workflow_step_runs", type_="unique"
    )
