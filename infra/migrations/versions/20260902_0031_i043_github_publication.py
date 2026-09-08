"""Persist exact, approved GitHub publication reconciliations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260902_0031"
down_revision = "20260902_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "github_publication_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("git_commit_action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("git_commit_actions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("approval_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("binding_version", sa.String(32), nullable=False),
        sa.Column("repository_identity", postgresql.JSONB(), nullable=False),
        sa.Column("base_branch", sa.String(255), nullable=False),
        sa.Column("prepared_remote_base_sha", sa.String(40), nullable=False),
        sa.Column("branch_ref", sa.String(255), nullable=False),
        sa.Column("local_parent_sha", sa.String(40), nullable=False),
        sa.Column("local_tree_sha", sa.String(40), nullable=False),
        sa.Column("local_commit_sha", sa.String(40), nullable=False),
        sa.Column("changeset_proof", postgresql.JSONB(), nullable=False),
        sa.Column("pr_title", sa.String(160), nullable=False),
        sa.Column("pr_body", sa.String(16384), nullable=False),
        sa.Column("pr_body_hash", sa.String(64), nullable=False),
        sa.Column("publication_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_effect", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("remote_tree_sha", sa.String(40), nullable=True),
        sa.Column("remote_commit_sha", sa.String(40), nullable=True),
        sa.Column("remote_ref_sha", sa.String(40), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(2048), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("git_commit_action_id", name="uq_github_publication_git_action"),
        sa.UniqueConstraint("approval_request_id", name="uq_github_publication_approval"),
        sa.CheckConstraint("policy_effect = 'REQUIRE_CONFIRMATION'", name="ck_github_publication_policy"),
        sa.CheckConstraint("status IN ('PENDING_APPROVAL','PUBLISHING','PUBLISHED','FAILED','STALE','CONFLICT','REJECTED')", name="ck_github_publication_status"),
        sa.CheckConstraint("jsonb_typeof(repository_identity) = 'object'", name="ck_github_publication_repo_identity"),
        sa.CheckConstraint("jsonb_typeof(changeset_proof) = 'object'", name="ck_github_publication_changeset_proof"),
    )
    op.create_index("ix_github_publication_scope_created", "github_publication_actions", ["tenant_id", "workspace_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_github_publication_scope_created", table_name="github_publication_actions")
    op.drop_table("github_publication_actions")
