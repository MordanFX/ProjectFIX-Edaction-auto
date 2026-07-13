"""Per-lesson enrollment progress and scheduled availability."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from course_platform.db.base import Base
from course_platform.models.enums import LessonProgressStatus
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values

if TYPE_CHECKING:
    from course_platform.models.course import Lesson, LessonMaterial
    from course_platform.models.student import Enrollment


class LessonProgress(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "lesson_id", name="enrollment_lesson"),
    )

    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), index=True
    )
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[LessonProgressStatus] = mapped_column(
        Enum(
            LessonProgressStatus,
            name="lesson_progress_status",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        ),
        default=LessonProgressStatus.LOCKED,
        index=True,
    )
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    homework_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enrollment: Mapped[Enrollment] = relationship(back_populates="lesson_progress")
    lesson: Mapped[Lesson] = relationship(back_populates="progress_records")


class LessonMaterialProgress(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lesson_material_progress"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "material_id", name="enrollment_material"),
    )

    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), index=True
    )
    material_id: Mapped[UUID] = mapped_column(
        ForeignKey("lesson_materials.id", ondelete="CASCADE"), index=True
    )
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    enrollment: Mapped[Enrollment] = relationship()
    material: Mapped[LessonMaterial] = relationship()
