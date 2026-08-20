"""Project persistence model."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novalton_api.modules.workspaces.models import Workspace


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project owned by exactly one workspace."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 200", name="ck_projects_name_length"),
        CheckConstraint("char_length(slug) BETWEEN 1 AND 63", name="ck_projects_slug_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 4000",
            name="ck_projects_description_length",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'PAUSED', 'ARCHIVED')",
            name="ck_projects_status_value",
        ),
        UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_id_slug"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            name="fk_projects_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")

    workspace: Mapped["Workspace"] = relationship(back_populates="projects")
