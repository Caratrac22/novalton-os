"""Human financial consent and monotonically consumed reservations.

These records do not enable a provider. A caller must still pass its own
provider, operator, dispatch and environment checks before any network I/O.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class FinancialAuthorization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT",
            name="fk_financial_project_scope",
        ),
        CheckConstraint("version > 0", name="ck_financial_version"),
        CheckConstraint(
            "request_limit > 0 AND request_count >= 0 AND request_count <= request_limit",
            name="ck_financial_requests",
        ),
        CheckConstraint(
            "token_limit > 0 AND reserved_tokens >= 0 AND reserved_tokens <= token_limit",
            name="ck_financial_tokens",
        ),
        CheckConstraint(
            "estimated_limit >= 0 AND reserved_estimate >= 0 "
            "AND reserved_estimate <= estimated_limit",
            name="ck_financial_estimate",
        ),
        CheckConstraint("expires_at > created_at", name="ck_financial_expiry"),
        CheckConstraint(
            "char_length(provider_id) BETWEEN 1 AND 64 AND char_length(model_id) BETWEEN 1 AND 256",
            name="ck_financial_model",
        ),
        Index("ix_financial_scope", "owner_id", "tenant_id", "workspace_id", "project_id"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("human_operators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_limit: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    reserved_estimate: Mapped[Decimal] = mapped_column(
        Numeric(20, 10), nullable=False, default=Decimal(0)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinancialReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "financial_reservations"
    __table_args__ = (
        UniqueConstraint("authorization_id", "request_id", name="uq_financial_reservation_request"),
        CheckConstraint("tokens > 0 AND estimate >= 0", name="ck_financial_reservation_amount"),
    )

    authorization_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("financial_authorizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    estimate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
