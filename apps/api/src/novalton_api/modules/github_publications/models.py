from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class GitHubPublicationAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "github_publication_actions"
    __table_args__ = (
        UniqueConstraint("git_commit_action_id", name="uq_github_publication_git_action"),
        UniqueConstraint("approval_request_id", name="uq_github_publication_approval"),
        CheckConstraint(
            "policy_effect = 'REQUIRE_CONFIRMATION'", name="ck_github_publication_policy"
        ),
        CheckConstraint(
            "status IN ("
            "'PENDING_APPROVAL','PUBLISHING','PUBLISHED','FAILED','STALE','CONFLICT','REJECTED'"
            ")",
            name="ck_github_publication_status",
        ),
        Index(
            "ix_github_publication_scope_created", "tenant_id", "workspace_id", "created_at", "id"
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT")
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT")
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT")
    )
    task_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT")
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="RESTRICT")
    )
    git_commit_action_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("git_commit_actions.id", ondelete="RESTRICT")
    )
    approval_request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="RESTRICT")
    )
    binding_version: Mapped[str] = mapped_column(String(32))
    repository_identity: Mapped[dict[str, object]] = mapped_column(JSONB)
    base_branch: Mapped[str] = mapped_column(String(255))
    prepared_remote_base_sha: Mapped[str] = mapped_column(String(40))
    branch_ref: Mapped[str] = mapped_column(String(255))
    local_parent_sha: Mapped[str] = mapped_column(String(40))
    local_tree_sha: Mapped[str] = mapped_column(String(40))
    local_commit_sha: Mapped[str] = mapped_column(String(40))
    changeset_proof: Mapped[dict[str, object]] = mapped_column(JSONB)
    pr_title: Mapped[str] = mapped_column(String(160))
    pr_body: Mapped[str] = mapped_column(String(16384))
    pr_body_hash: Mapped[str] = mapped_column(String(64))
    publication_fingerprint: Mapped[str] = mapped_column(String(64))
    policy_effect: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    remote_tree_sha: Mapped[str | None] = mapped_column(String(40))
    remote_commit_sha: Mapped[str | None] = mapped_column(String(40))
    remote_ref_sha: Mapped[str | None] = mapped_column(String(40))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(2048))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
