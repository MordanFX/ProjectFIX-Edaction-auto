"""Central lesson progression rules shared by the bot and curator workflows."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Lesson,
    LessonProgress,
    Student,
)
from course_platform.models.enums import (
    EnrollmentStatus,
    LessonProgressStatus,
    UnlockRule,
)
from course_platform.services.reminders import LessonReminderService


class ProgressionError(RuntimeError):
    pass


class ActiveLessonNotFoundError(ProgressionError):
    pass


class LessonMismatchError(ProgressionError):
    pass


@dataclass(frozen=True, slots=True)
class ProgressionResult:
    enrollment_id: UUID
    lesson_id: UUID
    lesson_position: int
    status: LessonProgressStatus
    current_lesson_position: int
    course_completed: bool
    next_lesson_available: bool


@dataclass(frozen=True, slots=True)
class _ProgressionContext:
    enrollment: Enrollment
    lesson: Lesson
    course: Course


class ProgressionService:
    """Apply view, submission, and acceptance events through one rule engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def mark_current_viewed(
        self,
        telegram_user_id: int,
        *,
        expected_lesson_id: UUID | None = None,
    ) -> ProgressionResult:
        async with session_scope(self._session_factory) as session:
            context = (
                await session.execute(
                    select(Enrollment, Lesson, Course)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(Cohort, Cohort.id == Enrollment.cohort_id)
                    .join(Course, Course.id == Cohort.course_id)
                    .join(
                        Lesson,
                        (Lesson.course_id == Course.id)
                        & (Lesson.position == Enrollment.current_lesson_position),
                    )
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Student.is_active.is_(True),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Course.is_active.is_(True),
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).one_or_none()
            if context is None:
                raise ActiveLessonNotFoundError

            enrollment, lesson, course = context
            if expected_lesson_id is not None and lesson.id != expected_lesson_id:
                raise LessonMismatchError
            return await self._record_viewed(
                session,
                _ProgressionContext(enrollment=enrollment, lesson=lesson, course=course),
            )

    @classmethod
    async def ensure_current_available(
        cls,
        session: AsyncSession,
        *,
        enrollment: Enrollment,
        lesson: Lesson,
    ) -> LessonProgress:
        progress = await cls._get_or_create_progress(session, enrollment=enrollment, lesson=lesson)
        now = cls._now_for(progress.release_at)
        if (
            progress.status is LessonProgressStatus.LOCKED
            and lesson.position == enrollment.current_lesson_position
            and cls._release_reached(progress.release_at, now)
        ):
            progress.status = LessonProgressStatus.AVAILABLE
            progress.available_at = now
        if progress.status is LessonProgressStatus.AVAILABLE:
            available_at = progress.available_at or now
            progress.available_at = available_at
            await LessonReminderService.ensure_scheduled(
                session,
                enrollment=enrollment,
                lesson=lesson,
                available_at=available_at,
            )
        return progress

    @classmethod
    async def record_submission(
        cls,
        session: AsyncSession,
        *,
        enrollment_id: UUID,
        lesson_id: UUID,
        occurred_at: datetime | None = None,
    ) -> ProgressionResult:
        context = await cls._load_context(
            session,
            enrollment_id=enrollment_id,
            lesson_id=lesson_id,
        )
        progress = await cls._get_or_create_progress(
            session,
            enrollment=context.enrollment,
            lesson=context.lesson,
        )
        now = occurred_at or cls._now_for(progress.release_at)
        progress.homework_submitted_at = now
        await LessonReminderService.cancel_pending(
            session,
            enrollment_id=context.enrollment.id,
            lesson_id=context.lesson.id,
        )

        if (
            context.course.unlock_rule is UnlockRule.AFTER_SUBMISSION
            and context.enrollment.current_lesson_position == context.lesson.position
        ):
            progress.status = LessonProgressStatus.COMPLETED
            progress.completed_at = now
            return await cls._advance(session, context=context, progress=progress, now=now)

        if progress.status is not LessonProgressStatus.COMPLETED:
            progress.status = LessonProgressStatus.HOMEWORK_SUBMITTED
        return cls._result(context=context, progress=progress)

    @classmethod
    async def record_review(
        cls,
        session: AsyncSession,
        *,
        enrollment_id: UUID,
        lesson_id: UUID,
        accepted: bool,
        occurred_at: datetime | None = None,
    ) -> ProgressionResult:
        context = await cls._load_context(
            session,
            enrollment_id=enrollment_id,
            lesson_id=lesson_id,
        )
        progress = await cls._get_or_create_progress(
            session,
            enrollment=context.enrollment,
            lesson=context.lesson,
        )
        now = occurred_at or cls._now_for(progress.release_at)

        if not accepted:
            if progress.status is not LessonProgressStatus.COMPLETED:
                progress.status = (
                    LessonProgressStatus.VIEWED
                    if progress.viewed_at is not None
                    else LessonProgressStatus.AVAILABLE
                )
            return cls._result(context=context, progress=progress)

        progress.status = LessonProgressStatus.COMPLETED
        progress.completed_at = now
        if (
            context.course.unlock_rule is UnlockRule.AFTER_ACCEPTANCE
            and context.enrollment.current_lesson_position == context.lesson.position
        ):
            return await cls._advance(session, context=context, progress=progress, now=now)
        return cls._result(context=context, progress=progress)

    @classmethod
    async def _record_viewed(
        cls,
        session: AsyncSession,
        context: _ProgressionContext,
    ) -> ProgressionResult:
        progress = await cls.ensure_current_available(
            session,
            enrollment=context.enrollment,
            lesson=context.lesson,
        )
        now = cls._now_for(progress.release_at)
        if progress.status is LessonProgressStatus.LOCKED:
            return cls._result(context=context, progress=progress)

        progress.viewed_at = progress.viewed_at or now
        await LessonReminderService.cancel_pending(
            session,
            enrollment_id=context.enrollment.id,
            lesson_id=context.lesson.id,
        )
        required_assignment = await session.scalar(
            select(Assignment.is_required).where(Assignment.lesson_id == context.lesson.id)
        )
        if (
            context.course.unlock_rule is UnlockRule.AFTER_VIEW
            or required_assignment is not True
        ):
            progress.status = LessonProgressStatus.COMPLETED
            progress.completed_at = now
            return await cls._advance(session, context=context, progress=progress, now=now)

        if progress.status is LessonProgressStatus.AVAILABLE:
            progress.status = LessonProgressStatus.VIEWED
        return cls._result(context=context, progress=progress)

    @classmethod
    async def _advance(
        cls,
        session: AsyncSession,
        *,
        context: _ProgressionContext,
        progress: LessonProgress,
        now: datetime,
    ) -> ProgressionResult:
        next_lesson = await session.scalar(
            select(Lesson)
            .where(
                Lesson.course_id == context.course.id,
                Lesson.position > context.lesson.position,
                Lesson.is_published.is_(True),
            )
            .order_by(Lesson.position)
            .limit(1)
        )
        if next_lesson is None:
            context.enrollment.status = EnrollmentStatus.COMPLETED
            return cls._result(context=context, progress=progress)

        context.enrollment.current_lesson_position = next_lesson.position
        next_progress = await cls._get_or_create_progress(
            session,
            enrollment=context.enrollment,
            lesson=next_lesson,
        )
        if (
            next_progress.status is LessonProgressStatus.LOCKED
            and cls._release_reached(next_progress.release_at, now)
        ):
            next_progress.status = LessonProgressStatus.AVAILABLE
            next_progress.available_at = now
        if next_progress.status is LessonProgressStatus.AVAILABLE:
            available_at = next_progress.available_at or now
            next_progress.available_at = available_at
            await LessonReminderService.ensure_scheduled(
                session,
                enrollment=context.enrollment,
                lesson=next_lesson,
                available_at=available_at,
            )

        return ProgressionResult(
            enrollment_id=context.enrollment.id,
            lesson_id=context.lesson.id,
            lesson_position=context.lesson.position,
            status=progress.status,
            current_lesson_position=context.enrollment.current_lesson_position,
            course_completed=False,
            next_lesson_available=next_progress.status is not LessonProgressStatus.LOCKED,
        )

    @staticmethod
    async def _load_context(
        session: AsyncSession,
        *,
        enrollment_id: UUID,
        lesson_id: UUID,
    ) -> _ProgressionContext:
        row = (
            await session.execute(
                select(Enrollment, Lesson, Course)
                .join(Cohort, Cohort.id == Enrollment.cohort_id)
                .join(Course, Course.id == Cohort.course_id)
                .join(Lesson, Lesson.course_id == Course.id)
                .where(Enrollment.id == enrollment_id, Lesson.id == lesson_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise ActiveLessonNotFoundError
        enrollment, lesson, course = row
        return _ProgressionContext(enrollment=enrollment, lesson=lesson, course=course)

    @classmethod
    async def _get_or_create_progress(
        cls,
        session: AsyncSession,
        *,
        enrollment: Enrollment,
        lesson: Lesson,
    ) -> LessonProgress:
        progress = await session.scalar(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.lesson_id == lesson.id,
            )
        )
        if progress is not None:
            return progress

        release_at = enrollment.created_at + timedelta(hours=lesson.release_offset_hours)
        now = cls._now_for(release_at)
        if enrollment.status is EnrollmentStatus.COMPLETED or lesson.position < (
            enrollment.current_lesson_position
        ):
            status = LessonProgressStatus.COMPLETED
            available_at = enrollment.created_at
            completed_at = enrollment.updated_at or now
        elif lesson.position == enrollment.current_lesson_position and cls._release_reached(
            release_at, now
        ):
            status = LessonProgressStatus.AVAILABLE
            available_at = now
            completed_at = None
        else:
            status = LessonProgressStatus.LOCKED
            available_at = None
            completed_at = None

        progress = LessonProgress(
            enrollment_id=enrollment.id,
            lesson_id=lesson.id,
            status=status,
            release_at=release_at,
            available_at=available_at,
            completed_at=completed_at,
        )
        session.add(progress)
        await session.flush()
        return progress

    @staticmethod
    def _release_reached(release_at: datetime | None, now: datetime) -> bool:
        return release_at is None or now >= release_at

    @staticmethod
    def _now_for(reference: datetime | None) -> datetime:
        now = datetime.now(UTC)
        if reference is not None and reference.tzinfo is None:
            return now.replace(tzinfo=None)
        return now

    @staticmethod
    def _result(
        *,
        context: _ProgressionContext,
        progress: LessonProgress,
    ) -> ProgressionResult:
        return ProgressionResult(
            enrollment_id=context.enrollment.id,
            lesson_id=context.lesson.id,
            lesson_position=context.lesson.position,
            status=progress.status,
            current_lesson_position=context.enrollment.current_lesson_position,
            course_completed=context.enrollment.status is EnrollmentStatus.COMPLETED,
            next_lesson_available=False,
        )
