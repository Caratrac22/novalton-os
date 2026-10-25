"""Human authorization of a bounded disposable test launch.

Revision ID: 20261026_0048
Revises: 20261025_0047
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261026_0048"
down_revision = "20261025_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "launch_authorizations",
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
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("human_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "compilation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cadrage_compilations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(256), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("max_model_calls", sa.Integer(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "financial_authorization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("financial_authorizations.id", ondelete="RESTRICT"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT",
            name="fk_launch_project_scope",
        ),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_launch_owner_request"),
        sa.CheckConstraint(
            "source_version > 0 AND proposal_version > 0 AND version > 0",
            name="ck_launch_versions",
        ),
        sa.CheckConstraint(
            "max_model_calls BETWEEN 1 AND 100 AND max_duration_seconds BETWEEN 1 AND 3600",
            name="ck_launch_limits",
        ),
        sa.CheckConstraint(
            "environment = 'DISPOSABLE_TEST'", name="ck_launch_environment"
        ),
        sa.CheckConstraint(
            "provider_id = 'local' AND char_length(model_id) BETWEEN 1 AND 256",
            name="ck_launch_local_model",
        ),
        sa.CheckConstraint(
            "char_length(fingerprint) = 64", name="ck_launch_fingerprint"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_launch_expiry"),
    )


def downgrade() -> None:
    op.drop_table("launch_authorizations")
