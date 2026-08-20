"""Task persistence model."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from novalton_api.core.database import Base
from novalton_api.core.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from novalton_api.modules.projects.models import Project


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user objective owned by exactly one project."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("char_length(title) BETWEEN 1 AND 200", name="ck_tasks_title_length"),
        CheckConstraint(
            "description IS NULL OR char_length(description) <= 4000",
            name="ck_tasks_description_length",
        ),
        CheckConstraint(
            "status IN ('BACKLOG', 'READY', 'IN_PROGRESS', 'BLOCKED', 'REVIEW', "
            "'DONE', 'CANCELLED')",
            name="ck_tasks_status_value",
        ),
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", name="fk_tasks_project_id_projects", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="BACKLOG")

    project: Mapped["Project"] = relationship(back_populates="tasks")
