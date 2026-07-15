"""Discord identities, link codes, and personal homework spaces."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from course_platform.db.base import Base
from course_platform.models.mixins import PrimaryKeyMixin, TimestampMixin


class DiscordParticipant(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "discord_student_links"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_user_id", name="discord_link_guild_user"),
        UniqueConstraint("guild_id", "student_id", name="discord_link_guild_student"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(100), default="Discord participant")
    username: Mapped[str | None] = mapped_column(String(64))
    global_name: Mapped[str | None] = mapped_column(String(100))
    avatar_hash: Mapped[str | None] = mapped_column(String(128))
    guild_joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_guild_member: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Compatibility name for the historical table and migration chain.
DiscordStudentLink = DiscordParticipant


class DiscordLinkCode(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "discord_link_codes"

    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    code_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscordInvite(PrimaryKeyMixin, TimestampMixin, Base):
    """Onboarding link a curator created for a new Discord student.

    Path 1 onboarding: the student joins with a plain Discord invite and then
    opens ``/homework`` to create their private thread. We keep this record only
    so a curator can see the links they handed out and not lose the URL. There
    is deliberately no usage tracking here — that would require the bot to read
    guild invites (``Manage Server``), which we do not grant.
    """

    __tablename__ = "discord_invites"
    __table_args__ = (
        UniqueConstraint("code", name="discord_invite_code"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    code: Mapped[str] = mapped_column(String(64), index=True)
    invite_url: Mapped[str] = mapped_column(String(255))
    course_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    max_age_seconds: Mapped[int] = mapped_column(default=86400, server_default="86400")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), index=True
    )


class DiscordHomeworkSpace(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "discord_homework_spaces"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_user_id", name="discord_guild_user"),
        UniqueConstraint("channel_id", name="discord_homework_channel"),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    parent_channel_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    channel_name: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(100))
    student_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), index=True
    )


class DiscordQuestion(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "discord_questions"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "channel_id",
            "message_id",
            name="discord_question_message",
        ),
    )

    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discord_student_links.id", ondelete="SET NULL"), index=True
    )
    student_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), index=True
    )
    text_body: Mapped[str | None] = mapped_column(Text)
    attachment_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open", index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL"), index=True
    )
