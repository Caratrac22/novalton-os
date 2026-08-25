"""Widen the I-048 catalog output metadata bound."""

from alembic import op

revision: str = "20260825_0016"
down_revision: str | None = "20260825_0015"
branch_labels: None = None
depends_on: None = None

_CONSTRAINT = "ck_model_definitions_max_output_tokens_value"
_MAX_CATALOG_OUTPUT_TOKENS = 10_000_000


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "model_definitions", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "model_definitions",
        f"max_output_tokens IS NULL OR max_output_tokens BETWEEN 1 AND {_MAX_CATALOG_OUTPUT_TOKENS}",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "model_definitions", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "model_definitions",
        "max_output_tokens IS NULL OR max_output_tokens BETWEEN 1 AND 65536",
    )
