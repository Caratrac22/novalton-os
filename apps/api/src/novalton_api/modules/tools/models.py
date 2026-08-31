"""Durable safe metadata for governed tool attempts and results."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class ToolCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One exact model proposal and its governed local execution outcome."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "call_key", name="uq_tool_calls_agent_run_call_key"),
        CheckConstraint(
            "char_length(tool_id) BETWEEN 1 AND 100", name="ck_tool_calls_tool_id_length"
        ),
        CheckConstraint(
            "char_length(call_key) BETWEEN 1 AND 100", name="ck_tool_calls_call_key_length"
        ),
        CheckConstraint(
            "status IN ('PROPOSED','PENDING_APPROVAL','RUNNING','SUCCEEDED','FAILED','BLOCKED')",
            name="ck_tool_calls_status_value",
        ),
        CheckConstraint(
            "policy_effect IS NULL OR policy_effect IN "
            "('ALLOW','ALLOW_WITH_LOG','REQUIRE_CONFIRMATION','BLOCK')",
            name="ck_tool_calls_policy_effect_value",
        ),
        CheckConstraint("execution_target_class = 'LOCAL'", name="ck_tool_calls_target_local"),
        CheckConstraint("side_effect_class = 'READ_ONLY'", name="ck_tool_calls_read_only"),
        CheckConstraint(
            "failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 64",
            name="ck_tool_calls_failure_code_length",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_tool_calls_timestamp_order",
        ),
        CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL", name="ck_tool_calls_task_requires_project"
        ),
        CheckConstraint(
            "jsonb_typeof(safe_input_metadata) = 'object'",
            name="ck_tool_calls_safe_input_shape",
        ),
        CheckConstraint(
            "jsonb_typeof(matched_rule_ids) = 'array' AND "
            "jsonb_array_length(matched_rule_ids) <= 64",
            name="ck_tool_calls_matched_rules_shape",
        ),
        CheckConstraint(
            "result_metadata IS NULL OR jsonb_typeof(result_metadata) = 'object'",
            name="ck_tool_calls_result_shape",
        ),
        CheckConstraint(
            "(status IN ('PROPOSED','PENDING_APPROVAL') AND started_at IS NULL "
            "AND completed_at IS NULL) OR (status = 'RUNNING' AND started_at IS NOT NULL "
            "AND completed_at IS NULL) OR (status IN ('SUCCEEDED','FAILED') "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status = 'BLOCKED' AND completed_at IS NOT NULL)",
            name="ck_tool_calls_lifecycle_shape",
        ),
        Index("ix_tool_calls_scope_created", "tenant_id", "workspace_id", "created_at", "id"),
        Index("ix_tool_calls_agent_created", "agent_run_id", "created_at", "id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=True
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True
    )
    agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    proposal_model_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("model_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    approval_request_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="RESTRICT"),
        nullable=True,
    )
    call_key: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(100), nullable=False)
    safe_input_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    policy_effect: Mapped[str | None] = mapped_column(String(24), nullable=True)
    matched_rule_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    execution_target_class: Mapped[str] = mapped_column(String(16), nullable=False, default="LOCAL")
    side_effect_class: Mapped[str] = mapped_column(String(16), nullable=False, default="READ_ONLY")
    result_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
