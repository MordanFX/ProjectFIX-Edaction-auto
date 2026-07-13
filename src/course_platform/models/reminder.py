"""Course reminder policies and durable lesson reminder queue."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from course_platform.db.base import Base
from course_platform.models.enums import ReminderKind, ReminderStatus
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values

if TYPE_CHECKING:
    from course_platform.models.course import Course, Lesson
    from course_platform.models.student import Enrollment


class CourseReminderStep(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "course_reminder_steps"
    __table_args__ = (
        UniqueConstraint("course_id", "sequence", name="course_reminder_sequence"),
        CheckConstraint("sequence > 0", name="positive_reminder_sequence"),
        CheckConstraint("delay_hours >= 0", name="non_negative_reminder_delay"),
    )

    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    delay_hours: Mapped[int] = mapped_column(Integer)
    kind: Mapped[ReminderKind] = mapped_column(
        Enum(
            ReminderKind,
            name="reminder_kind",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    message_text: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    course: Mapped[Course] = relationship(back_populates="reminder_steps")
    reminders: Mapped[list[LessonReminder]] = relationship(
        back_populates="step", cascade="all, delete-orphan"
    )


class LessonReminder(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lesson_reminders"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "lesson_id", "step_id", name="lesson_reminder_step"),
    )

    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), index=True
    )
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[UUID] = mapped_column(
        ForeignKey("course_reminder_steps.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(
            ReminderStatus,
            name="reminder_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=ReminderStatus.PENDING,
        index=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)

    enrollment: Mapped[Enrollment] = relationship(back_populates="lesson_reminders")
    lesson: Mapped[Lesson] = relationship(back_populates="reminders")
    step: Mapped[CourseReminderStep] = relationship(back_populates="reminders")
