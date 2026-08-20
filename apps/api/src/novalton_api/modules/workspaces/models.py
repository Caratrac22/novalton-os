"""Workspace persistence model."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novalton_api.modules.projects.models import Project
    from novalton_api.modules.tenants.models import Tenant


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant-scoped operational boundary."""

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="ck_workspaces_name_length"),
        CheckConstraint("char_length(slug) BETWEEN 1 AND 63", name="ck_workspaces_slug_length"),
        UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_id_slug"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("tenants.id", name="fk_workspaces_tenant_id_tenants", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="workspaces")
    projects: Mapped[list["Project"]] = relationship(back_populates="workspace")
