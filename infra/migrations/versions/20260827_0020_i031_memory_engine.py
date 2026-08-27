"""Add I-031 scoped temporal structured memory.

Revision ID: 20260827_0020
Revises: 20260826_0019
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260827_0020"
down_revision: str | None = "20260826_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "memory_records",
        sa.Column("workspace_id", uuid, nullable=False),
        sa.Column("project_id", uuid, nullable=True),
        sa.Column("task_id", uuid, nullable=True),
        sa.Column("workflow_run_id", uuid, nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("knowledge_state", sa.String(24), nullable=False),
        sa.Column("statement", sa.String(2000), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("id", uuid, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('FACT', 'DECISION', 'PREFERENCE', 'CONSTRAINT', 'EVENT', 'NOTE')",
            name="ck_memory_records_kind_value",
        ),
        sa.CheckConstraint(
            "knowledge_state IN ('CONFIRMED_FACT', 'OBSERVED_FACT', 'INFERENCE', 'HYPOTHESIS', 'DISPUTED', 'OBSOLETE')",
            name="ck_memory_records_knowledge_state_value",
        ),
        sa.CheckConstraint(
            "char_length(statement) BETWEEN 1 AND 2000",
            name="ck_memory_records_statement_length",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_memory_records_confidence_range",
        ),
        sa.CheckConstraint(
            "importance BETWEEN 1 AND 5", name="ck_memory_records_importance_range"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_memory_records_valid_interval",
        ),
        sa.CheckConstraint(
            "lifecycle IN ('ACTIVE', 'ARCHIVED')",
            name="ck_memory_records_lifecycle_value",
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_memory_records_task_requires_project",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_records_workspace_created_id",
        "memory_records",
        ["workspace_id", "created_at", "id"],
    )
    op.create_index(
        "ix_memory_records_workspace_kind", "memory_records", ["workspace_id", "kind"]
    )
    op.create_index(
        "ix_memory_records_workspace_knowledge_state",
        "memory_records",
        ["workspace_id", "knowledge_state"],
    )
    op.create_index(
        "ix_memory_records_workspace_project",
        "memory_records",
        ["workspace_id", "project_id"],
    )
    op.create_table(
        "memory_provenance",
        sa.Column("memory_id", uuid, nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_reference_id", sa.String(256), nullable=True),
        sa.Column("id", uuid, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('USER_STATEMENT', 'TOOL_OBSERVATION', 'DOCUMENT', 'AGENT_RESULT', 'SYSTEM_EVENT', 'DERIVED_FROM_MEMORY', 'MANUAL_EDIT')",
            name="ck_memory_provenance_source_type_value",
        ),
        sa.CheckConstraint(
            "source_reference_id IS NULL OR char_length(source_reference_id) BETWEEN 1 AND 256",
            name="ck_memory_provenance_source_reference_length",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["memory_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_provenance_memory_id", "memory_provenance", ["memory_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_provenance_memory_id", table_name="memory_provenance")
    op.drop_table("memory_provenance")
    op.drop_index("ix_memory_records_workspace_project", table_name="memory_records")
    op.drop_index(
        "ix_memory_records_workspace_knowledge_state", table_name="memory_records"
    )
    op.drop_index("ix_memory_records_workspace_kind", table_name="memory_records")
    op.drop_index("ix_memory_records_workspace_created_id", table_name="memory_records")
    op.drop_table("memory_records")
