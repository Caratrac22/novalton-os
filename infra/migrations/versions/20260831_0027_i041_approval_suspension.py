"""Add durable approval suspension and one-round continuation guards."""

import sqlalchemy as sa
from alembic import op

revision = "20260831_0027"
down_revision = "20260831_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_agent_runs_lifecycle_shape", "agent_runs", type_="check")
    op.drop_constraint("ck_agent_runs_status_value", "agent_runs", type_="check")
    op.alter_column(
        "agent_runs", "status", type_=sa.String(24), existing_type=sa.String(16)
    )
    op.create_check_constraint(
        "ck_agent_runs_status_value",
        "agent_runs",
        "status IN ('CREATED','RUNNING','WAITING_FOR_APPROVAL','SUCCEEDED','FAILED','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_agent_runs_lifecycle_shape",
        "agent_runs",
        "(status = 'CREATED' AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status IN ('RUNNING','WAITING_FOR_APPROVAL') AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status = 'SUCCEEDED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
        "(status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
        "(status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
    )

    op.drop_constraint(
        "ck_workflow_step_runs_lifecycle_shape", "workflow_step_runs", type_="check"
    )
    op.drop_constraint(
        "ck_workflow_step_runs_status_value", "workflow_step_runs", type_="check"
    )
    op.alter_column(
        "workflow_step_runs", "status", type_=sa.String(24), existing_type=sa.String(16)
    )
    op.create_check_constraint(
        "ck_workflow_step_runs_status_value",
        "workflow_step_runs",
        "status IN ('PENDING','READY','RUNNING','WAITING_FOR_APPROVAL','COMPLETED','FAILED','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_workflow_step_runs_lifecycle_shape",
        "workflow_step_runs",
        "(status IN ('PENDING','READY') AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status IN ('RUNNING','WAITING_FOR_APPROVAL') AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status = 'COMPLETED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
        "(status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
        "(status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
    )
    op.create_index(
        "uq_model_runs_agent_tool_continuation",
        "model_runs",
        ["agent_run_id"],
        unique=True,
        postgresql_where=sa.text("recovery_attempt_kind = 'TOOL_CONTINUATION'"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_runs_agent_tool_continuation", table_name="model_runs")
    op.drop_constraint(
        "ck_workflow_step_runs_lifecycle_shape", "workflow_step_runs", type_="check"
    )
    op.drop_constraint(
        "ck_workflow_step_runs_status_value", "workflow_step_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_workflow_step_runs_status_value",
        "workflow_step_runs",
        "status IN ('PENDING','READY','RUNNING','COMPLETED','FAILED','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_workflow_step_runs_lifecycle_shape",
        "workflow_step_runs",
        "(status IN ('PENDING','READY') AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status = 'COMPLETED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
        "(status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
        "(status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
    )
    op.alter_column(
        "workflow_step_runs", "status", type_=sa.String(16), existing_type=sa.String(24)
    )
    op.drop_constraint("ck_agent_runs_lifecycle_shape", "agent_runs", type_="check")
    op.drop_constraint("ck_agent_runs_status_value", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_status_value",
        "agent_runs",
        "status IN ('CREATED','RUNNING','SUCCEEDED','FAILED','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_agent_runs_lifecycle_shape",
        "agent_runs",
        "(status = 'CREATED' AND started_at IS NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status = 'RUNNING' AND started_at IS NOT NULL AND completed_at IS NULL AND failure_code IS NULL) OR "
        "(status = 'SUCCEEDED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NULL) OR "
        "(status = 'FAILED' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND failure_code IS NOT NULL) OR "
        "(status = 'CANCELLED' AND completed_at IS NOT NULL AND failure_code IS NULL)",
    )
    op.alter_column(
        "agent_runs", "status", type_=sa.String(16), existing_type=sa.String(24)
    )
