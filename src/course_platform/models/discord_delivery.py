"""Curator-created Discord lesson dispatches and per-participant deliveries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from course_platform.db.base import Base
from course_platform.models.enums import NotificationStatus
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values


class DiscordLessonDispatch(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "discord_lesson_dispatches"

    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True
    )
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_users.id", ondelete="RESTRICT"), index=True
    )
    custom_message: Mapped[str | None] = mapped_column(Text)
    recipient_count: Mapped[int] = mapped_column(Integer)


class DiscordLessonDelivery(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "discord_lesson_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id",
            "participant_id",
            name="discord_lesson_participant_delivery",
        ),
    )

    dispatch_id: Mapped[UUID] = mapped_column(
        ForeignKey("discord_lesson_dispatches.id", ondelete="CASCADE"), index=True
    )
    lesson_id: Mapped[UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("discord_student_links.id", ondelete="CASCADE"), index=True
    )
    discord_user_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(
            NotificationStatus,
            name="discord_lesson_delivery_status",
            native_enum=False,
            values_callable=enum_values,
        ),
        default=NotificationStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger)
