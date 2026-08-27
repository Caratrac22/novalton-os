"""Add I-032 PostgreSQL lexical retrieval index.

Revision ID: 20260827_0021
Revises: 20260827_0020
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0021"
down_revision: str | None = "20260827_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_memory_records_statement_fts",
        "memory_records",
        [sa.text("to_tsvector('simple', statement)")],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_memory_records_statement_fts", table_name="memory_records")
