"""Persistent deterministic policy rules."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class PolicyRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant rule, optionally narrowed to one workspace."""

    __tablename__ = "policy_rules"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="ck_policy_rules_name_length"),
        CheckConstraint(
            "char_length(action_pattern) BETWEEN 1 AND 100",
            name="ck_policy_rules_action_pattern_length",
        ),
        CheckConstraint(
            "effect IN ('ALLOW', 'ALLOW_WITH_LOG', 'REQUIRE_CONFIRMATION', 'BLOCK')",
            name="ck_policy_rules_effect_value",
        ),
        CheckConstraint(
            "actor_type IS NULL OR char_length(actor_type) BETWEEN 1 AND 64",
            name="ck_policy_rules_actor_type_length",
        ),
        CheckConstraint(
            "resource_type IS NULL OR char_length(resource_type) BETWEEN 1 AND 64",
            name="ck_policy_rules_resource_type_length",
        ),
        Index(
            "ix_policy_rules_scope_enabled_action",
            "tenant_id",
            "workspace_id",
            "enabled",
            "action_pattern",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_policy_rules_tenant_id_tenants", ondelete="RESTRICT"),
        nullable=False,
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            name="fk_policy_rules_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    action_pattern: Mapped[str] = mapped_column(String(100), nullable=False)
    effect: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conditions_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
