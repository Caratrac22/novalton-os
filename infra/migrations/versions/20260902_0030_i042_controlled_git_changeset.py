"""Persist exact post-QA local Git changesets.

Revision ID: 20260902_0030
Revises: 20260901_0029
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260902_0030"
down_revision = "20260901_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "git_commit_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("approval_requests.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("repository_key", sa.String(64), nullable=False), sa.Column("branch_ref", sa.String(255), nullable=False), sa.Column("prepared_head_sha", sa.String(40), nullable=False), sa.Column("index_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_tool_call_ids", postgresql.JSONB(), nullable=False), sa.Column("prepared_paths", postgresql.JSONB(), nullable=False), sa.Column("preview", postgresql.JSONB(), nullable=False),
        sa.Column("commit_message", sa.String(200), nullable=False), sa.Column("author_identity", sa.String(200), nullable=False), sa.Column("committer_identity", sa.String(200), nullable=False), sa.Column("commit_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action_fingerprint", sa.String(64), nullable=False), sa.Column("policy_effect", sa.String(24), nullable=False), sa.Column("expected_commit_sha", sa.String(40), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("resulting_commit_sha", sa.String(40), nullable=True), sa.Column("failure_code", sa.String(64), nullable=True), sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("approval_request_id", name="uq_git_commit_actions_approval"),
        sa.CheckConstraint("status IN ('PENDING_APPROVAL','APPLYING','APPLIED','FAILED','REJECTED')", name="ck_git_commit_actions_status"), sa.CheckConstraint("policy_effect = 'REQUIRE_CONFIRMATION'", name="ck_git_commit_actions_policy"), sa.CheckConstraint("action_fingerprint ~ '^[a-f0-9]{64}$'", name="ck_git_commit_actions_fp"), sa.CheckConstraint("prepared_head_sha ~ '^[a-f0-9]{40}$'", name="ck_git_commit_actions_head"), sa.CheckConstraint("expected_commit_sha ~ '^[a-f0-9]{40}$'", name="ck_git_commit_actions_commit"), sa.CheckConstraint("resulting_commit_sha IS NULL OR resulting_commit_sha ~ '^[a-f0-9]{40}$'", name="ck_git_commit_actions_result"), sa.CheckConstraint("jsonb_typeof(source_tool_call_ids) = 'array'", name="ck_git_commit_actions_sources"), sa.CheckConstraint("jsonb_typeof(prepared_paths) = 'array'", name="ck_git_commit_actions_paths"), sa.CheckConstraint("jsonb_typeof(preview) = 'object'", name="ck_git_commit_actions_preview"), sa.CheckConstraint("failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'", name="ck_git_commit_actions_failure"),
    )
    op.create_index("ix_git_commit_actions_scope_created", "git_commit_actions", ["tenant_id", "workspace_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_git_commit_actions_scope_created", table_name="git_commit_actions")
    op.drop_table("git_commit_actions")
