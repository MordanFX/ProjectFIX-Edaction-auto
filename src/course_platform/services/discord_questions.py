"""Discord student question queue for curator follow-up."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    DiscordHomeworkSpace,
    DiscordParticipant,
    DiscordQuestion,
    StaffUser,
    Student,
)


class DiscordQuestionAccessError(PermissionError):
    """The message does not belong to the member's private homework thread."""


@dataclass(frozen=True, slots=True)
class DiscordQuestionOverview:
    question_id: UUID
    guild_id: int
    channel_id: int
    message_id: int
    discord_user_id: int
    student_id: UUID | None
    student_name: str | None
    discord_display_name: str | None
    discord_username: str | None
    text_body: str | None
    attachment_count: int
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None


class DiscordQuestionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_from_message(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        channel_id: int,
        message_id: int,
        text: str,
        attachment_count: int,
    ) -> DiscordQuestionOverview:
        async with session_scope(self._session_factory) as session:
            existing = await self._question_by_message(
                session,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            if existing is not None:
                return existing
            participant = await session.scalar(
                select(DiscordParticipant)
                .join(
                    DiscordHomeworkSpace,
                    (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                    & (
                        DiscordHomeworkSpace.discord_user_id
                        == DiscordParticipant.discord_user_id
                    ),
                )
                .where(
                    DiscordParticipant.guild_id == guild_id,
                    DiscordParticipant.discord_user_id == discord_user_id,
                    DiscordHomeworkSpace.channel_id == channel_id,
                )
                .limit(1)
            )
            if participant is None:
                raise DiscordQuestionAccessError
            question = DiscordQuestion(
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                discord_user_id=discord_user_id,
                participant_id=participant.id,
                student_id=participant.student_id,
                text_body=text.strip() or None,
                attachment_count=attachment_count,
            )
            session.add(question)
            await session.flush()
            return await self._question_by_id(session, question.id)

    async def list_questions(
        self,
        *,
        guild_id: int | None = None,
        include_resolved: bool = True,
    ) -> list[DiscordQuestionOverview]:
        async with self._session_factory() as session:
            query = (
                select(DiscordQuestion, DiscordParticipant, Student, StaffUser)
                .outerjoin(
                    DiscordParticipant,
                    DiscordParticipant.id == DiscordQuestion.participant_id,
                )
                .outerjoin(Student, Student.id == DiscordQuestion.student_id)
                .outerjoin(StaffUser, StaffUser.id == DiscordQuestion.resolved_by_staff_id)
                .order_by(DiscordQuestion.created_at.desc())
            )
            if guild_id is not None:
                query = query.where(DiscordQuestion.guild_id == guild_id)
            if not include_resolved:
                query = query.where(DiscordQuestion.status == "open")
            return [self._overview(*row) for row in (await session.execute(query)).all()]

    async def resolve_question(
        self,
        *,
        question_id: UUID,
        staff_id: UUID,
    ) -> DiscordQuestionOverview | None:
        async with session_scope(self._session_factory) as session:
            question = await session.get(DiscordQuestion, question_id)
            if question is None:
                return None
            question.status = "resolved"
            question.resolved_at = datetime.now(UTC)
            question.resolved_by_staff_id = staff_id
            await session.flush()
            return await self._question_by_id(session, question.id)

    async def resolve_latest_open_in_channel(
        self,
        *,
        guild_id: int,
        channel_id: int,
        responder_discord_user_id: int,
    ) -> DiscordQuestionOverview | None:
        """Close the latest open question when someone else replies in the private thread."""
        async with session_scope(self._session_factory) as session:
            question = await session.scalar(
                select(DiscordQuestion)
                .where(
                    DiscordQuestion.guild_id == guild_id,
                    DiscordQuestion.channel_id == channel_id,
                    DiscordQuestion.status == "open",
                    DiscordQuestion.discord_user_id != responder_discord_user_id,
                )
                .order_by(DiscordQuestion.created_at.desc())
                .limit(1)
            )
            if question is None:
                return None
            question.status = "resolved"
            question.resolved_at = datetime.now(UTC)
            await session.flush()
            return await self._question_by_id(session, question.id)

    async def _question_by_message(
        self,
        session: AsyncSession,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> DiscordQuestionOverview | None:
        row = (
            await session.execute(
                select(DiscordQuestion, DiscordParticipant, Student, StaffUser)
                .outerjoin(
                    DiscordParticipant,
                    DiscordParticipant.id == DiscordQuestion.participant_id,
                )
                .outerjoin(Student, Student.id == DiscordQuestion.student_id)
                .outerjoin(StaffUser, StaffUser.id == DiscordQuestion.resolved_by_staff_id)
                .where(
                    DiscordQuestion.guild_id == guild_id,
                    DiscordQuestion.channel_id == channel_id,
                    DiscordQuestion.message_id == message_id,
                )
            )
        ).one_or_none()
        return self._overview(*row) if row else None

    async def _question_by_id(
        self,
        session: AsyncSession,
        question_id: UUID,
    ) -> DiscordQuestionOverview:
        row = (
            await session.execute(
                select(DiscordQuestion, DiscordParticipant, Student, StaffUser)
                .outerjoin(
                    DiscordParticipant,
                    DiscordParticipant.id == DiscordQuestion.participant_id,
                )
                .outerjoin(Student, Student.id == DiscordQuestion.student_id)
                .outerjoin(StaffUser, StaffUser.id == DiscordQuestion.resolved_by_staff_id)
                .where(DiscordQuestion.id == question_id)
            )
        ).one()
        return self._overview(*row)

    @staticmethod
    def _overview(
        question: DiscordQuestion,
        participant: DiscordParticipant | None,
        student: Student | None,
        staff: StaffUser | None,
    ) -> DiscordQuestionOverview:
        return DiscordQuestionOverview(
            question_id=question.id,
            guild_id=question.guild_id,
            channel_id=question.channel_id,
            message_id=question.message_id,
            discord_user_id=question.discord_user_id,
            student_id=question.student_id,
            student_name=student.first_name if student else None,
            discord_display_name=participant.display_name if participant else None,
            discord_username=participant.username if participant else None,
            text_body=question.text_body,
            attachment_count=question.attachment_count,
            status=question.status,
            created_at=question.created_at,
            resolved_at=question.resolved_at,
            resolved_by=staff.display_name if staff else None,
        )
