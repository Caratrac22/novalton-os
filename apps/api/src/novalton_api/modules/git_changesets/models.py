"""Durable, operator-authorized local Git changesets."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class GitCommitAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One prepared exact changeset and, at most, one local branch update."""

    __tablename__ = "git_commit_actions"
    __table_args__ = (
        UniqueConstraint("approval_request_id", name="uq_git_commit_actions_approval"),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPLYING','APPLIED','FAILED','REJECTED')",
            name="ck_git_commit_actions_status",
        ),
        CheckConstraint(
            "policy_effect = 'REQUIRE_CONFIRMATION'", name="ck_git_commit_actions_policy"
        ),
        CheckConstraint("action_fingerprint ~ '^[a-f0-9]{64}$'", name="ck_git_commit_actions_fp"),
        CheckConstraint("prepared_head_sha ~ '^[a-f0-9]{40}$'", name="ck_git_commit_actions_head"),
        CheckConstraint(
            "expected_commit_sha ~ '^[a-f0-9]{40}$'", name="ck_git_commit_actions_commit"
        ),
        CheckConstraint(
            "resulting_commit_sha IS NULL OR resulting_commit_sha ~ '^[a-f0-9]{40}$'",
            name="ck_git_commit_actions_result",
        ),
        CheckConstraint(
            "jsonb_typeof(source_tool_call_ids) = 'array'", name="ck_git_commit_actions_sources"
        ),
        CheckConstraint(
            "jsonb_typeof(prepared_paths) = 'array'", name="ck_git_commit_actions_paths"
        ),
        CheckConstraint("jsonb_typeof(preview) = 'object'", name="ck_git_commit_actions_preview"),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_git_commit_actions_failure",
        ),
        Index(
            "ix_git_commit_actions_scope_created", "tenant_id", "workspace_id", "created_at", "id"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approval_request_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="RESTRICT"),
        nullable=True,
    )
    repository_key: Mapped[str] = mapped_column(String(64), nullable=False)
    branch_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    prepared_head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    index_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_tool_call_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    prepared_paths: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    commit_message: Mapped[str] = mapped_column(String(200), nullable=False)
    author_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    committer_identity: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_effect: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    resulting_commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
