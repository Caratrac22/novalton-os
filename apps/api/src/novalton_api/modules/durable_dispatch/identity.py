"""Durable human identity and explicit workspace permission for operator decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class HumanOperator(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "human_operators"
    __table_args__ = (
        CheckConstraint("char_length(label) BETWEEN 1 AND 128", name="ck_human_operator_label"),
    )

    label: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TenantOperatorMembership(Base):
    """Explicit human membership; workspace grants narrow its authority."""

    __tablename__ = "tenant_operator_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('OWNER','ADMIN','MEMBER','VIEWER')", name="ck_operator_membership_role"
        ),
        CheckConstraint(
            "(active AND revoked_at IS NULL) OR (NOT active AND revoked_at IS NOT NULL)",
            name="ck_operator_membership_revocation",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("human_operators.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkspaceOperatorPermission(Base):
    __tablename__ = "workspace_operator_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
            name="fk_operator_permission_workspace_scope",
        ),
        CheckConstraint(
            "permission IN ('activation.configure','dispatch.enqueue','dispatch.read',"
            "'dispatch.cancel','dispatch.resolve')",
            name="ck_operator_permission_name",
        ),
        CheckConstraint(
            "(active AND revoked_at IS NULL) OR (NOT active AND revoked_at IS NOT NULL)",
            name="ck_operator_permission_revocation",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("human_operators.id", ondelete="RESTRICT", name="fk_operator_permission_user"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    permission: Mapped[str] = mapped_column(String(32), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
