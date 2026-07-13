"""Courses, cohorts, lessons, and assignments."""

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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from course_platform.db.base import Base
from course_platform.models.enums import CourseAudience, SubmissionKind, UnlockRule, VideoSource
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values

if TYPE_CHECKING:
    from course_platform.models.progress import LessonProgress
    from course_platform.models.reminder import CourseReminderStep, LessonReminder
    from course_platform.models.student import Enrollment
    from course_platform.models.submission import Submission


class Course(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "courses"

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[CourseAudience] = mapped_column(
        Enum(
            CourseAudience,
            name="course_audience",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=CourseAudience.TELEGRAM,
        server_default=CourseAudience.TELEGRAM.value,
        index=True,
    )
    unlock_rule: Mapped[UnlockRule] = mapped_column(
        Enum(UnlockRule, name="unlock_rule", native_enum=False, values_callable=enum_values),
        default=UnlockRule.AFTER_ACCEPTANCE,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    cohorts: Mapped[list[Cohort]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="Lesson.position"
    )
    reminder_steps: Mapped[list[CourseReminderStep]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseReminderStep.sequence",
    )


class Cohort(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cohorts"
    __table_args__ = (UniqueConstraint("course_id", "title", name="course_title"),)

    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    course: Mapped[Course] = relationship(back_populates="cohorts")
    enrollments: Mapped[list[Enrollment]] = relationship(
        back_populates="cohort", cascade="all, delete-orphan"
    )


class Lesson(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("course_id", "position", name="course_position"),
        CheckConstraint("position > 0", name="positive_position"),
        CheckConstraint("release_offset_hours >= 0", name="non_negative_release_offset"),
    )

    course_id: Mapped[UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    video_source: Mapped[VideoSource] = mapped_column(
        Enum(VideoSource, name="video_source", native_enum=False, values_callable=enum_values),
        default=VideoSource.PLACEHOLDER,
    )
    video_reference: Mapped[str | None] = mapped_column(Text)
    release_offset_hours: Mapped[int] = mapped_column(default=0, server_default="0")
    requires_view_confirmation: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
    )
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    course: Mapped[Course] = relationship(back_populates="lessons")
    assignment: Mapped[Assignment | None] = relationship(
        back_populates="lesson", cascade="all, delete-orphan", single_parent=True
    )
    progress_records: Mapped[list[LessonProgress]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )
    reminders: Mapped[list[LessonReminder]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )
    materials: Mapped[list[LessonMaterial]] = relationship(
        back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="LessonMaterial.position",
    )


class LessonMaterial(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "lesson_materials"
    __table_args__ = (
        UniqueConstraint("lesson_id", "position", name="lesson_material_position"),
        CheckConstraint("position > 0", name="positive_material_position"),
    )

    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32), default="video", server_default="video")
    video_source: Mapped[VideoSource] = mapped_column(
        Enum(VideoSource, name="video_source", native_enum=False, values_callable=enum_values),
        default=VideoSource.PLACEHOLDER,
    )
    video_reference: Mapped[str | None] = mapped_column(Text)

    lesson: Mapped[Lesson] = relationship(back_populates="materials")


class Assignment(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assignments"

    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), unique=True, index=True
    )
    instructions: Mapped[str] = mapped_column(Text)
    submission_kind: Mapped[SubmissionKind] = mapped_column(
        Enum(
            SubmissionKind,
            name="submission_kind",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=SubmissionKind.ANY,
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    lesson: Mapped[Lesson] = relationship(back_populates="assignment")
    submissions: Mapped[list[Submission]] = relationship(back_populates="assignment")
