"""Allow accounting for registered provider-managed virtual routes."""

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0017"
down_revision: str | None = "20260825_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "model_runs", "model_definition_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )


def downgrade() -> None:
    op.alter_column(
        "model_runs", "model_definition_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )
