"""Homework submissions, Telegram attachments, and curator feedback."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from course_platform.db.base import Base
from course_platform.models.enums import (
    AttachmentKind,
    FeedbackVerdict,
    NotificationStatus,
    SubmissionSource,
    SubmissionStatus,
)
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values

if TYPE_CHECKING:
    from course_platform.models.course import Assignment
    from course_platform.models.staff import StaffUser
    from course_platform.models.student import Enrollment, Student


class Submission(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "assignment_id", "attempt_number", name="attempt"),
        UniqueConstraint(
            "source_channel_id",
            "source_message_id",
            name="discord_submission_message",
        ),
        CheckConstraint("attempt_number > 0", name="positive_attempt_number"),
    )

    enrollment_id: Mapped[UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), index=True
    )
    assignment_id: Mapped[UUID] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(default=1)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(
            SubmissionStatus,
            name="submission_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=SubmissionStatus.SUBMITTED,
        index=True,
    )
    text_body: Mapped[str | None] = mapped_column(Text)
    source: Mapped[SubmissionSource] = mapped_column(
        Enum(
            SubmissionSource,
            name="submission_source",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=SubmissionSource.TELEGRAM,
        server_default=SubmissionSource.TELEGRAM.value,
        index=True,
    )
    source_guild_id: Mapped[int | None] = mapped_column(BigInteger)
    source_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), index=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enrollment: Mapped[Enrollment] = relationship(back_populates="submissions")
    assignment: Mapped[Assignment] = relationship(back_populates="submissions")
    assigned_reviewer: Mapped[StaffUser | None] = relationship(
        foreign_keys=[assigned_reviewer_id]
    )
    attachments: Mapped[list[SubmissionAttachment]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )
    feedback: Mapped[Feedback | None] = relationship(
        back_populates="submission", cascade="all, delete-orphan", single_parent=True
    )


class SubmissionAttachment(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "submission_attachments"

    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AttachmentKind] = mapped_column(
        Enum(
            AttachmentKind,
            name="attachment_kind",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255), index=True)
    discord_attachment_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    external_url: Mapped[str | None] = mapped_column(Text)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None]
    file_name: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None]
    width: Mapped[int | None]
    height: Mapped[int | None]

    submission: Mapped[Submission] = relationship(back_populates="attachments")


class Feedback(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), unique=True, index=True
    )
    reviewer_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_users.id", ondelete="RESTRICT"), index=True
    )
    verdict: Mapped[FeedbackVerdict] = mapped_column(
        Enum(
            FeedbackVerdict,
            name="feedback_verdict",
            native_enum=False,
            values_callable=enum_values,
        )
    )
    message: Mapped[str] = mapped_column(Text)
    notification_status: Mapped[NotificationStatus] = mapped_column(
        Enum(
            NotificationStatus,
            name="notification_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=NotificationStatus.PENDING,
        index=True,
    )
    notification_attempts: Mapped[int] = mapped_column(default=0)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_error: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[Submission] = relationship(back_populates="feedback")
    reviewer: Mapped[StaffUser] = relationship(back_populates="feedback_items")
    attachments: Mapped[list[FeedbackAttachment]] = relationship(
        back_populates="feedback", cascade="all, delete-orphan"
    )


class FeedbackAttachment(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback_attachments"

    feedback_id: Mapped[UUID] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AttachmentKind] = mapped_column(
        Enum(
            AttachmentKind,
            name="feedback_attachment_kind",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255), index=True)
    discord_attachment_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    external_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    file_name: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None]
    width: Mapped[int | None]
    height: Mapped[int | None]

    feedback: Mapped[Feedback] = relationship(back_populates="attachments")


class TelegramQuestion(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telegram_questions"

    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    assignment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assignments.id", ondelete="SET NULL"), index=True
    )
    text_body: Mapped[str | None] = mapped_column(Text)
    attachment_kind: Mapped[AttachmentKind | None] = mapped_column(
        Enum(
            AttachmentKind,
            name="telegram_question_attachment_kind",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    attachment_telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    attachment_telegram_file_unique_id: Mapped[str | None] = mapped_column(String(255))
    attachment_file_name: Mapped[str | None] = mapped_column(String(512))
    attachment_mime_type: Mapped[str | None] = mapped_column(String(255))
    attachment_file_size: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open", index=True
    )
    answer_text: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), index=True
    )

    student: Mapped[Student] = relationship()
    assignment: Mapped[Assignment | None] = relationship()
    resolved_by: Mapped[StaffUser | None] = relationship()
