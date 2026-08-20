"""Tenant persistence model."""

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An organization-level ownership boundary."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="ck_tenants_name_length"),
        CheckConstraint("char_length(slug) BETWEEN 1 AND 63", name="ck_tenants_slug_length"),
        UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)

    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="tenant")


from novalton_api.modules.workspaces.models import Workspace  # noqa: E402
