"""Store provider generation identity and authenticated usage observations."""

from alembic import op
from sqlalchemy import text

revision = "20261021_0039"
down_revision = "20261021_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE model_runs ADD COLUMN provider_generation_id varchar(128)")
    op.execute("""
        ALTER TABLE model_runs ADD CONSTRAINT ck_model_runs_provider_generation_id_length
            CHECK (provider_generation_id IS NULL OR char_length(provider_generation_id) BETWEEN 1 AND 128)
    """)
    op.execute("""
        CREATE TABLE provider_cost_observations (
            model_run_id uuid PRIMARY KEY REFERENCES model_runs(id) ON DELETE RESTRICT,
            provider_id varchar(64) NOT NULL,
            generation_id varchar(128) NOT NULL,
            reported_cost numeric(20, 10) NOT NULL,
            response_sha256 varchar(64) NOT NULL,
            observed_at timestamptz NOT NULL,
            CONSTRAINT uq_provider_cost_generation UNIQUE (provider_id, generation_id),
            CONSTRAINT ck_provider_cost_non_negative CHECK (reported_cost >= 0)
        )
    """)


def downgrade() -> None:
    if op.get_bind().scalar(
        text("SELECT EXISTS (SELECT 1 FROM provider_cost_observations)")
    ):
        raise RuntimeError("provider_cost_observation_downgrade_has_history")
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM model_runs WHERE provider_generation_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("provider_generation_identity_downgrade_has_history")
    op.drop_table("provider_cost_observations")
    op.drop_constraint("ck_model_runs_provider_generation_id_length", "model_runs")
    op.drop_column("model_runs", "provider_generation_id")
