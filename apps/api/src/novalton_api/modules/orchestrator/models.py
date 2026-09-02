"""Durable human resolution of one exact Agent challenge."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import UUIDPrimaryKeyMixin


class AgentChallengeResolution(UUIDPrimaryKeyMixin, Base):
    """One immutable challenge identity with at most one trusted human decision."""

    __tablename__ = "agent_challenge_resolutions"
    __table_args__ = (
        UniqueConstraint("workflow_step_run_id", name="uq_agent_challenge_resolutions_step_run"),
        UniqueConstraint("agent_run_id", name="uq_agent_challenge_resolutions_agent_run"),
        CheckConstraint(
            "challenge_level IN ('HUMAN_REVIEW_RECOMMENDED', 'BLOCK_RECOMMENDED')",
            name="ck_agent_challenge_resolutions_level",
        ),
        CheckConstraint(
            "result_status IN ('COMPLETED', 'PARTIAL')",
            name="ck_agent_challenge_resolutions_result_status",
        ),
        CheckConstraint(
            "specialization_role IS NULL OR specialization_role IN "
            "('developer_manager', 'developer_worker', 'qa_worker')",
            name="ck_agent_challenge_resolutions_role",
        ),
        CheckConstraint(
            "qa_verdict IS NULL OR qa_verdict IN "
            "('PASS', 'PASS_WITH_WARNINGS', 'FAIL', 'INCONCLUSIVE')",
            name="ck_agent_challenge_resolutions_qa_verdict",
        ),
        CheckConstraint(
            "(specialization_role = 'qa_worker' AND qa_verdict IS NOT NULL) OR "
            "(specialization_role IS DISTINCT FROM 'qa_worker' AND qa_verdict IS NULL)",
            name="ck_agent_challenge_resolutions_qa_role_verdict",
        ),
        CheckConstraint(
            "safe_review_summary IS NULL OR specialization_role = 'qa_worker'",
            name="ck_agent_challenge_resolutions_review_role",
        ),
        CheckConstraint(
            "safe_review_summary IS NULL OR "
            "(jsonb_typeof(safe_review_summary) = 'object' "
            "AND octet_length(safe_review_summary::text) <= 524288)",
            name="ck_agent_challenge_resolutions_review_shape",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('ACCEPT_RESULT', 'REJECT_RESULT')",
            name="ck_agent_challenge_resolutions_decision",
        ),
        CheckConstraint(
            "challenge_level != 'BLOCK_RECOMMENDED' OR decision IS NULL "
            "OR decision = 'REJECT_RESULT'",
            name="ck_agent_challenge_resolutions_block_decision",
        ),
        CheckConstraint(
            "reason IS NULL OR char_length(reason) BETWEEN 1 AND 500",
            name="ck_agent_challenge_resolutions_reason",
        ),
        CheckConstraint(
            "(decision IS NULL AND decision_actor_type IS NULL AND decision_actor_id IS NULL "
            "AND reason IS NULL AND decided_at IS NULL) OR "
            "(decision IS NOT NULL AND decision_actor_type = 'local_user' "
            "AND decision_actor_id IS NULL AND decided_at IS NOT NULL)",
            name="ck_agent_challenge_resolutions_decision_state",
        ),
        Index(
            "ix_agent_challenge_resolutions_scope_created",
            "tenant_id",
            "workspace_id",
            "created_at",
            "id",
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
    workflow_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_step_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workflow_step_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    challenge_level: Mapped[str] = mapped_column(String(32), nullable=False)
    result_status: Mapped[str] = mapped_column(String(16), nullable=False)
    specialization_role: Mapped[str | None] = mapped_column(String(24), nullable=True)
    qa_verdict: Mapped[str | None] = mapped_column(String(24), nullable=True)
    safe_review_summary: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decision_actor_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    decision_actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
