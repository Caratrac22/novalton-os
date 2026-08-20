"""Add I-014 one-action approval requests.

Revision ID: 20260820_0008
Revises: 20260820_0007
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0008"
down_revision: str = "20260820_0007"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    """Create only the explicitly scoped approval request table."""
    op.create_table(
        "approval_requests",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("requester_actor_type", sa.String(length=16), nullable=False),
        sa.Column("requester_actor_id", sa.String(length=128), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("policy_effect", sa.String(length=24), nullable=False),
        sa.Column(
            "matched_rule_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "policy_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("decision_actor_type", sa.String(length=16), nullable=True),
        sa.Column("decision_actor_id", sa.String(length=128), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "char_length(action) BETWEEN 3 AND 100",
            name="ck_approval_requests_action_length",
        ),
        sa.CheckConstraint(
            "requester_actor_type IN ('api', 'agent', 'model', 'service', 'tool')",
            name="ck_approval_requests_requester_actor_type_value",
        ),
        sa.CheckConstraint(
            "requester_actor_id IS NULL OR char_length(requester_actor_id) BETWEEN 1 AND 128",
            name="ck_approval_requests_requester_actor_id_length",
        ),
        sa.CheckConstraint(
            "resource_type IS NULL OR char_length(resource_type) BETWEEN 1 AND 64",
            name="ck_approval_requests_resource_type_length",
        ),
        sa.CheckConstraint(
            "(resource_type IS NULL) = (resource_id IS NULL)",
            name="ck_approval_requests_resource_pair",
        ),
        sa.CheckConstraint(
            "task_id IS NULL OR project_id IS NOT NULL",
            name="ck_approval_requests_task_requires_project",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="ck_approval_requests_status_value",
        ),
        sa.CheckConstraint(
            "scope_type = 'ONE_ACTION'", name="ck_approval_requests_scope_type_value"
        ),
        sa.CheckConstraint(
            "policy_effect = 'REQUIRE_CONFIRMATION'",
            name="ck_approval_requests_policy_effect_value",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(matched_rule_ids) = 'array' AND "
            "jsonb_array_length(matched_rule_ids) <= 64",
            name="ck_approval_requests_matched_rule_ids_shape",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(policy_reasons) = 'array' AND jsonb_array_length(policy_reasons) <= 64",
            name="ck_approval_requests_policy_reasons_shape",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decision_actor_type IS NULL AND decision_actor_id IS NULL "
            "AND decided_at IS NULL) OR (status IN ('APPROVED', 'REJECTED') "
            "AND decision_actor_type = 'local_user' AND decision_actor_id IS NULL "
            "AND decided_at IS NOT NULL)",
            name="ck_approval_requests_decision_state",
        ),
        sa.CheckConstraint(
            "correlation_id IS NULL OR char_length(correlation_id) BETWEEN 1 AND 128",
            name="ck_approval_requests_correlation_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_approval_requests_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_approval_requests_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_approval_requests_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_approval_requests_task_id_tasks",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_approval_requests_scope_requested_at_id",
        "approval_requests",
        ["tenant_id", "workspace_id", "requested_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove only the I-014 approval schema."""
    op.drop_index(
        "ix_approval_requests_scope_requested_at_id", table_name="approval_requests"
    )
    op.drop_table("approval_requests")
