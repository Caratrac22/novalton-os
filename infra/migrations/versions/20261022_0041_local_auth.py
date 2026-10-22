"""Local human credential, revocable opaque sessions and persistent login throttle.

Revision ID: 20261022_0041
Revises: 20261022_0040
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261022_0041"
down_revision = "20261022_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_credentials",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("login", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(login) BETWEEN 3 AND 128", name="ck_local_login"
        ),
    )
    op.create_table(
        "local_sessions",
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
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("expires_at > created_at", name="ck_local_session_expiry"),
    )
    op.create_index("ix_local_sessions_user", "local_sessions", ["user_id"])
    op.create_table(
        "local_login_throttles",
        sa.Column("login_sha256", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM local_credentials)")):
        raise RuntimeError("local_auth_downgrade_has_accounts")
    op.drop_table("local_login_throttles")
    op.drop_index("ix_local_sessions_user", table_name="local_sessions")
    op.drop_table("local_sessions")
    op.drop_table("local_credentials")
