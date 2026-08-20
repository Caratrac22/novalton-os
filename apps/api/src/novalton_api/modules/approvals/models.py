"""Persistent approval request and decision model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import UUIDPrimaryKeyMixin


class ApprovalRequest(UUIDPrimaryKeyMixin, Base):
    """Human authority for one exact proposed action; never an execution instruction."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "char_length(action) BETWEEN 3 AND 100", name="ck_approval_requests_action_length"
        ),
        CheckConstraint(
            "requester_actor_type IN ('api', 'agent', 'model', 'service', 'tool')",
            name="ck_approval_requests_requester_actor_type_value",
        ),
        CheckConstraint(
            "requester_actor_id IS NULL OR char_length(requester_actor_id) BETWEEN 1 AND 128",
            name="ck_approval_requests_requester_actor_id_length",
        ),
        CheckConstraint(
            "resource_type IS NULL OR char_length(resource_type) BETWEEN 1 AND 64",
            name="ck_approval_requests_resource_type_length",
        ),
        CheckConstraint(
            "(resource_type IS NULL) = (resource_id IS NULL)",
            name="ck_approval_requests_resource_pair",
        ),
        CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_approval_requests_task_requires_project",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_approval_requests_status_value",
        ),
        CheckConstraint("scope_type = 'ONE_ACTION'", name="ck_approval_requests_scope_type_value"),
        CheckConstraint(
            "policy_effect = 'REQUIRE_CONFIRMATION'",
            name="ck_approval_requests_policy_effect_value",
        ),
        CheckConstraint(
            "jsonb_typeof(matched_rule_ids) = 'array' AND "
            "jsonb_array_length(matched_rule_ids) <= 64",
            name="ck_approval_requests_matched_rule_ids_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(policy_reasons) = 'array' AND jsonb_array_length(policy_reasons) <= 64",
            name="ck_approval_requests_policy_reasons_shape",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND decision_actor_type IS NULL AND decision_actor_id IS NULL "
            "AND decided_at IS NULL) OR (status IN ('APPROVED', 'REJECTED') "
            "AND decision_actor_type = 'local_user' AND decision_actor_id IS NULL "
            "AND decided_at IS NOT NULL)",
            name="ck_approval_requests_decision_state",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_approval_requests_correlation_id_length",
        ),
        Index(
            "ix_approval_requests_scope_requested_at_id",
            "tenant_id",
            "workspace_id",
            "requested_at",
            "id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "tenants.id", name="fk_approval_requests_tenant_id_tenants", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            name="fk_approval_requests_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    requester_actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    requester_actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "projects.id", name="fk_approval_requests_project_id_projects", ondelete="RESTRICT"
        ),
        nullable=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tasks.id", name="fk_approval_requests_task_id_tasks", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="ONE_ACTION")
    policy_effect: Mapped[str] = mapped_column(String(24), nullable=False)
    matched_rule_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    policy_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    decision_actor_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
