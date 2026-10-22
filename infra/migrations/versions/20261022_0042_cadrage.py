"""Project scoped private chat history.

Revision ID: 20261022_0042
Revises: 20261022_0041
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261022_0042"
down_revision = "20261022_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_projects_id_workspace", "projects", ["id", "workspace_id"]
    )
    op.create_table(
        "cadrage_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("pending_request_id", postgresql.UUID(as_uuid=True)),
        sa.Column("pending_since", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="CASCADE",
            name="fk_cadrage_project_scope",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','NEEDS_MODEL','READY_FOR_REVIEW','APPROVED','REJECTED','NEEDS_CHANGES')",
            name="ck_cadrage_status",
        ),
    )
    op.create_index(
        "ix_cadrage_owner_project",
        "cadrage_conversations",
        ["tenant_id", "workspace_id", "project_id", "owner_id", "created_at", "id"],
    )
    op.create_table(
        "cadrage_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "reply_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_messages.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name="uq_cadrage_message_sequence"
        ),
        sa.UniqueConstraint(
            "conversation_id", "client_request_id", name="uq_cadrage_client_request"
        ),
        sa.UniqueConstraint("reply_to_id", name="uq_cadrage_assistant_reply"),
        sa.CheckConstraint("role IN ('USER','ASSISTANT')", name="ck_cadrage_role"),
        sa.CheckConstraint(
            "char_length(content) BETWEEN 1 AND 4000", name="ck_cadrage_content"
        ),
    )
    op.create_index(
        "ix_cadrage_messages_page", "cadrage_messages", ["conversation_id", "sequence"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM cadrage_conversations)")
    ):
        raise RuntimeError("cadrage_downgrade_has_history")
    op.drop_index("ix_cadrage_messages_page", table_name="cadrage_messages")
    op.drop_table("cadrage_messages")
    op.drop_index("ix_cadrage_owner_project", table_name="cadrage_conversations")
    op.drop_table("cadrage_conversations")
    op.drop_constraint("uq_projects_id_workspace", "projects", type_="unique")
