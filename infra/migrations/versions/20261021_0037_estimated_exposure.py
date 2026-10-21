"""Keep transactionally reserved estimates and catalog price provenance."""

from alembic import op
from sqlalchemy import text

revision = "20261021_0037"
down_revision = "20261021_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE task_dispatches
        ADD COLUMN max_estimated_exposure numeric(20,10),
        ADD COLUMN reserved_estimated_exposure numeric(20,10) NOT NULL DEFAULT 0,
        ADD CONSTRAINT ck_dispatch_estimated_exposure CHECK
          ((max_estimated_exposure IS NULL AND reserved_estimated_exposure >= 0)
           OR (max_estimated_exposure > 0 AND reserved_estimated_exposure >= 0
               AND reserved_estimated_exposure <= max_estimated_exposure
               AND NOT allow_unknown_cost))
    """)
    op.execute("""
        ALTER TABLE model_runs
        ADD COLUMN reserved_estimated_exposure numeric(20,10),
        ADD COLUMN price_verified_at_snapshot timestamptz,
        ADD CONSTRAINT ck_model_runs_reserved_exposure CHECK
            (reserved_estimated_exposure IS NULL OR reserved_estimated_exposure >= 0)
    """)


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM model_runs WHERE reserved_estimated_exposure IS NOT NULL)"
        )
    ) or connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM task_dispatches "
            "WHERE max_estimated_exposure IS NOT NULL OR reserved_estimated_exposure <> 0)"
        )
    ):
        raise RuntimeError("estimated_exposure_downgrade_has_history")
    op.execute(
        "ALTER TABLE model_runs DROP CONSTRAINT ck_model_runs_reserved_exposure, "
        "DROP COLUMN reserved_estimated_exposure, DROP COLUMN price_verified_at_snapshot"
    )
    op.execute(
        "ALTER TABLE task_dispatches DROP CONSTRAINT ck_dispatch_estimated_exposure, "
        "DROP COLUMN max_estimated_exposure, DROP COLUMN reserved_estimated_exposure"
    )
