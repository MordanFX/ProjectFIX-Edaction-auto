"""Read models for the independent curator-facing Discord workspace."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.models import (
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordParticipant,
    Enrollment,
    Lesson,
    Student,
    Submission,
)
from course_platform.models.enums import (
    AccessType,
    CourseAudience,
    EnrollmentStatus,
    SubmissionSource,
    SubmissionStatus,
)

DiscordMemberStatus = Literal[
    "active", "completed", "no_access", "left", "unregistered"
]


@dataclass(frozen=True, slots=True)
class DiscordMemberOverview:
    guild_id: int
    discord_user_id: int
    discord_display_name: str | None
    discord_username: str | None
    discord_global_name: str | None
    avatar_url: str | None
    student_id: UUID | None
    student_name: str | None
    enrollment_id: UUID | None
    course_id: UUID | None
    cohort_id: UUID | None
    course_title: str | None
    cohort_title: str | None
    enrollment_status: EnrollmentStatus | None
    access_type: AccessType | None
    current_lesson_position: int | None
    total_lessons: int
    channel_id: int | None
    thread_name: str | None
    space_kind: str | None
    status: DiscordMemberStatus
    is_guild_member: bool
    registered_at: datetime | None
    guild_joined_at: datetime | None
    last_activity_at: datetime | None
    left_at: datetime | None
    space_created_at: datetime | None
    total_submissions: int
    pending_submissions: int
    last_submission_at: datetime | None


@dataclass(frozen=True, slots=True)
class DiscordWorkspaceOverview:
    participants: int
    active_students: int
    private_spaces: int
    unregistered_spaces: int
    submissions_enabled: bool
    members: tuple[DiscordMemberOverview, ...]


class DiscordDashboardService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def overview(
        self,
        guild_id: int | None = None,
        *,
        submissions_enabled: bool = False,
    ) -> DiscordWorkspaceOverview:
        async with self._session_factory() as session:
            participants = await self._participants(session, guild_id)
            unregistered = await self._unregistered_spaces(session, guild_id)
            members = tuple((*participants, *unregistered))
            return DiscordWorkspaceOverview(
                participants=len(participants),
                active_students=sum(item.status == "active" for item in participants),
                private_spaces=sum(item.channel_id is not None for item in members),
                unregistered_spaces=len(unregistered),
                submissions_enabled=submissions_enabled,
                members=members,
            )

    async def _participants(
        self, session: AsyncSession, guild_id: int | None
    ) -> list[DiscordMemberOverview]:
        query = (
            select(
                DiscordParticipant,
                Student,
                DiscordHomeworkSpace,
                Enrollment,
                Cohort,
                Course,
            )
            .join(Student, Student.id == DiscordParticipant.student_id)
            .outerjoin(
                DiscordHomeworkSpace,
                (DiscordHomeworkSpace.guild_id == DiscordParticipant.guild_id)
                & (
                    DiscordHomeworkSpace.discord_user_id
                    == DiscordParticipant.discord_user_id
                ),
            )
            .outerjoin(Enrollment, Enrollment.student_id == Student.id)
            .outerjoin(Cohort, Cohort.id == Enrollment.cohort_id)
            .outerjoin(
                Course,
                and_(
                    Course.id == Cohort.course_id,
                    Course.audience == CourseAudience.DISCORD,
                ),
            )
            .order_by(DiscordParticipant.created_at.desc(), Enrollment.created_at.desc())
        )
        if guild_id is not None:
            query = query.where(DiscordParticipant.guild_id == guild_id)
        rows = (await session.execute(query)).all()
        submission_rows = (
            await session.execute(
                select(
                    Enrollment.student_id,
                    func.count(Submission.id),
                    func.sum(
                        case(
                            (
                                Submission.status.in_(
                                    (
                                        SubmissionStatus.SUBMITTED,
                                        SubmissionStatus.IN_REVIEW,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.max(Submission.submitted_at),
                )
                .join(Submission, Submission.enrollment_id == Enrollment.id)
                .where(Submission.source == SubmissionSource.DISCORD)
                .group_by(Enrollment.student_id)
            )
        ).all()
        submission_stats = {
            student_id: (total or 0, pending or 0, last_at)
            for student_id, total, pending, last_at in submission_rows
        }
        lesson_counts = dict(
            (
                await session.execute(
                    select(Lesson.course_id, func.count(Lesson.id)).group_by(
                        Lesson.course_id
                    )
                )
            ).all()
        )
        result: list[DiscordMemberOverview] = []
        seen: set[UUID] = set()
        for participant, student, space, enrollment, cohort, course in rows:
            if participant.id in seen:
                continue
            seen.add(participant.id)
            has_discord_course = course is not None
            total_submissions, pending_submissions, last_submission_at = (
                submission_stats.get(student.id, (0, 0, None))
            )
            result.append(
                DiscordMemberOverview(
                    guild_id=participant.guild_id,
                    discord_user_id=participant.discord_user_id,
                    discord_display_name=participant.display_name,
                    discord_username=participant.username,
                    discord_global_name=participant.global_name,
                    avatar_url=self._avatar_url(participant),
                    student_id=student.id,
                    student_name=student.first_name,
                    enrollment_id=enrollment.id if has_discord_course else None,
                    course_id=course.id if course else None,
                    cohort_id=cohort.id if has_discord_course else None,
                    course_title=course.title if course else None,
                    cohort_title=cohort.title if has_discord_course else None,
                    enrollment_status=(enrollment.status if has_discord_course else None),
                    access_type=(enrollment.access_type if has_discord_course else None),
                    current_lesson_position=(
                        enrollment.current_lesson_position if has_discord_course else None
                    ),
                    total_lessons=lesson_counts.get(course.id, 0) if course else 0,
                    channel_id=space.channel_id if space else None,
                    thread_name=space.channel_name if space else None,
                    space_kind=space.kind if space else None,
                    status=(
                        "left"
                        if not participant.is_guild_member
                        else "active"
                        if student.is_active
                        and has_discord_course
                        and enrollment.status is EnrollmentStatus.ACTIVE
                        else "completed"
                        if student.is_active
                        and has_discord_course
                        and enrollment.status is EnrollmentStatus.COMPLETED
                        else "no_access"
                    ),
                    is_guild_member=participant.is_guild_member,
                    registered_at=participant.created_at,
                    guild_joined_at=participant.guild_joined_at,
                    last_activity_at=participant.last_activity_at,
                    left_at=participant.left_at,
                    space_created_at=space.created_at if space else None,
                    total_submissions=total_submissions,
                    pending_submissions=pending_submissions,
                    last_submission_at=last_submission_at,
                )
            )
        return result

    async def _unregistered_spaces(
        self, session: AsyncSession, guild_id: int | None
    ) -> list[DiscordMemberOverview]:
        query = (
            select(DiscordHomeworkSpace)
            .outerjoin(
                DiscordParticipant,
                (DiscordParticipant.guild_id == DiscordHomeworkSpace.guild_id)
                & (
                    DiscordParticipant.discord_user_id
                    == DiscordHomeworkSpace.discord_user_id
                ),
            )
            .where(DiscordParticipant.id.is_(None))
            .order_by(DiscordHomeworkSpace.created_at.desc())
        )
        if guild_id is not None:
            query = query.where(DiscordHomeworkSpace.guild_id == guild_id)
        spaces = list(await session.scalars(query))
        return [
            DiscordMemberOverview(
                guild_id=space.guild_id,
                discord_user_id=space.discord_user_id,
                discord_display_name=space.display_name,
                discord_username=None,
                discord_global_name=None,
                avatar_url=None,
                student_id=None,
                student_name=space.display_name,
                enrollment_id=None,
                course_id=None,
                cohort_id=None,
                course_title=None,
                cohort_title=None,
                enrollment_status=None,
                access_type=None,
                current_lesson_position=None,
                total_lessons=0,
                channel_id=space.channel_id,
                thread_name=space.channel_name,
                space_kind=space.kind,
                status="unregistered",
                is_guild_member=True,
                registered_at=None,
                guild_joined_at=None,
                last_activity_at=None,
                left_at=None,
                space_created_at=space.created_at,
                total_submissions=0,
                pending_submissions=0,
                last_submission_at=None,
            )
            for space in spaces
        ]

    @staticmethod
    def _avatar_url(participant: DiscordParticipant) -> str:
        if participant.avatar_hash:
            return (
                "https://cdn.discordapp.com/avatars/"
                f"{participant.discord_user_id}/{participant.avatar_hash}.png?size=128"
            )
        index = (participant.discord_user_id >> 22) % 6
        return f"https://cdn.discordapp.com/embed/avatars/{index}.png"
