"""Students and their course enrollments."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from course_platform.db.base import Base
from course_platform.models.enums import (
    AccessType,
    ConversationState,
    EnrollmentStatus,
    StudentOrigin,
)
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values

if TYPE_CHECKING:
    from course_platform.models.course import Assignment, Cohort
    from course_platform.models.progress import LessonProgress
    from course_platform.models.reminder import LessonReminder
    from course_platform.models.submission import Submission


class Student(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "students"

    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    origin: Mapped[StudentOrigin] = mapped_column(
        Enum(
            StudentOrigin,
            name="student_origin",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=StudentOrigin.TELEGRAM,
        server_default=StudentOrigin.TELEGRAM.value,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    language_code: Mapped[str | None] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Europe/Kyiv",
        server_default="Europe/Kyiv",
    )
    quiet_hours_start: Mapped[int] = mapped_column(Integer, default=22, server_default="22")
    quiet_hours_end: Mapped[int] = mapped_column(Integer, default=9, server_default="9")
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    bot_state: Mapped[StudentBotState | None] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
        single_parent=True,
    )


class Enrollment(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "cohort_id", name="student_cohort"),
        CheckConstraint("current_lesson_position > 0", name="positive_lesson_position"),
    )

    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    cohort_id: Mapped[UUID] = mapped_column(
        ForeignKey("cohorts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        Enum(
            EnrollmentStatus,
            name="enrollment_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=EnrollmentStatus.ACTIVE,
    )
    access_type: Mapped[AccessType] = mapped_column(
        Enum(AccessType, name="access_type", native_enum=False, values_callable=enum_values),
        default=AccessType.MANUAL,
    )
    current_lesson_position: Mapped[int] = mapped_column(default=1)
    access_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    access_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    access_source: Mapped[str | None] = mapped_column(String(32))
    access_plan: Mapped[str | None] = mapped_column(String(32))

    student: Mapped[Student] = relationship(back_populates="enrollments")
    cohort: Mapped[Cohort] = relationship(back_populates="enrollments")
    submissions: Mapped[list[Submission]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )
    lesson_progress: Mapped[list[LessonProgress]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )
    lesson_reminders: Mapped[list[LessonReminder]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )


class StudentBotState(TimestampMixin, Base):
    __tablename__ = "student_bot_states"

    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[ConversationState] = mapped_column(
        Enum(
            ConversationState,
            name="conversation_state",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=ConversationState.IDLE,
    )
    assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )

    student: Mapped[Student] = relationship(back_populates="bot_state")
    assignment: Mapped[Assignment | None] = relationship()
