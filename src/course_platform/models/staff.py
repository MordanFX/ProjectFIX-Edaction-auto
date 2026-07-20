"""Curator and administrator identities."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from course_platform.db.base import Base
from course_platform.models.enums import FeedbackVerdict, StaffRole
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin
from course_platform.models.types import enum_values

if TYPE_CHECKING:
    from course_platform.models.submission import Feedback, Submission, TelegramQuestion


class StaffUser(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_users"

    login: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[StaffRole] = mapped_column(
        Enum(StaffRole, name="staff_role", native_enum=False, values_callable=enum_values),
        default=StaffRole.CURATOR,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    feedback_items: Mapped[list[Feedback]] = relationship(back_populates="reviewer")
    bot_state: Mapped[StaffBotState | None] = relationship(
        back_populates="staff",
        cascade="all, delete-orphan",
        single_parent=True,
    )


class StaffBotState(TimestampMixin, Base):
    """Durable pending feedback input for a Telegram curator."""

    __tablename__ = "staff_bot_states"

    staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_users.id", ondelete="CASCADE"), primary_key=True
    )
    submission_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[FeedbackVerdict | None] = mapped_column(
        Enum(
            FeedbackVerdict,
            name="feedback_verdict",
            native_enum=False,
            values_callable=enum_values,
        )
    )
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None]
    question_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_questions.id", ondelete="CASCADE"), index=True
    )

    staff: Mapped[StaffUser] = relationship(back_populates="bot_state")
    submission: Mapped[Submission | None] = relationship()
    question: Mapped[TelegramQuestion | None] = relationship()
