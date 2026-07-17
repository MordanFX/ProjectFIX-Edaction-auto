"""Student registration and progress use cases shared by all interfaces."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    CourseReminderStep,
    Enrollment,
    Lesson,
    LessonProgress,
    LessonReminder,
    Student,
    Submission,
)
from course_platform.models.enums import (
    AccessType,
    CourseAudience,
    EnrollmentStatus,
    LessonProgressStatus,
    ReminderStatus,
    StudentOrigin,
    SubmissionStatus,
)


@dataclass(frozen=True, slots=True)
class StudentRegistration:
    telegram_user_id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    student_id: UUID
    first_name: str
    is_new: bool


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    course_title: str
    current_lesson_position: int
    total_lessons: int
    accepted_submissions: int
    total_assignments: int


class StudentStage(StrEnum):
    NO_COURSE = "no_course"
    COURSE_COMPLETED = "course_completed"
    LESSON_LOCKED = "lesson_locked"
    NEEDS_VIEW = "needs_view"
    READY_TO_SUBMIT = "ready_to_submit"
    AWAITING_REVIEW = "awaiting_review"
    REVISION_REQUESTED = "revision_requested"


@dataclass(frozen=True, slots=True)
class StudentJourney:
    stage: StudentStage
    course_title: str | None
    lesson_position: int | None
    lesson_title: str | None
    release_at: datetime | None
    reminders_enabled: bool
    timezone: str
    quiet_hours_start: int
    quiet_hours_end: int


@dataclass(frozen=True, slots=True)
class TelegramCourseGrantStudent:
    student_id: UUID
    name: str
    username: str | None
    course_title: str | None
    current_lesson_position: int | None


@dataclass(frozen=True, slots=True)
class TelegramCourseGrantCourse:
    course_id: UUID
    title: str
    lessons_count: int
    students_count: int


class InvalidTimezoneError(ValueError):
    """Raised when a student selects an unknown IANA timezone."""


class InvalidQuietHoursError(ValueError):
    """Raised when quiet-hour boundaries are outside the supported range."""


class StudentService:
    """Register Telegram users and read their current course progress."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def register(self, registration: StudentRegistration) -> RegistrationResult:
        async with session_scope(self._session_factory) as session:
            student = await session.scalar(
                select(Student).where(Student.telegram_user_id == registration.telegram_user_id)
            )
            is_new = student is None

            if student is None:
                student = Student(
                    telegram_user_id=registration.telegram_user_id,
                    origin=StudentOrigin.TELEGRAM,
                    first_name=registration.first_name,
                )
                session.add(student)

            student.username = registration.username
            student.first_name = registration.first_name
            student.last_name = registration.last_name
            student.language_code = registration.language_code
            student.is_active = True
            student.last_activity_at = datetime.now(UTC)
            await session.flush()

            return RegistrationResult(
                student_id=student.id,
                first_name=student.first_name,
                is_new=is_new,
            )

    async def touch_activity(self, telegram_user_id: int) -> None:
        async with session_scope(self._session_factory) as session:
            student = await session.scalar(
                select(Student).where(Student.telegram_user_id == telegram_user_id)
            )
            if student is not None:
                student.last_activity_at = datetime.now(UTC)

    async def update_settings(
        self,
        telegram_user_id: int,
        *,
        timezone: str | None = None,
        quiet_hours: tuple[int, int] | None = None,
        reminders_enabled: bool | None = None,
    ) -> StudentJourney | None:
        """Update validated student-controlled notification settings."""

        if timezone is not None:
            try:
                ZoneInfo(timezone)
            except ZoneInfoNotFoundError:
                raise InvalidTimezoneError(timezone) from None

        if quiet_hours is not None and any(hour < 0 or hour > 23 for hour in quiet_hours):
            raise InvalidQuietHoursError(quiet_hours)

        async with session_scope(self._session_factory) as session:
            student = await session.scalar(
                select(Student).where(Student.telegram_user_id == telegram_user_id)
            )
            if student is None:
                return None

            if timezone is not None:
                student.timezone = timezone
            if quiet_hours is not None:
                student.quiet_hours_start, student.quiet_hours_end = quiet_hours
            if reminders_enabled is not None:
                student.reminders_enabled = reminders_enabled
                await self._sync_reminder_queue(
                    session,
                    student_id=student.id,
                    enabled=reminders_enabled,
                )

        return await self.get_journey(telegram_user_id)

    @staticmethod
    async def _sync_reminder_queue(
        session: AsyncSession,
        *,
        student_id: UUID,
        enabled: bool,
    ) -> None:
        if not enabled:
            reminders = list(
                await session.scalars(
                    select(LessonReminder)
                    .join(Enrollment, Enrollment.id == LessonReminder.enrollment_id)
                    .where(
                        Enrollment.student_id == student_id,
                        LessonReminder.status.in_(
                            [ReminderStatus.PENDING, ReminderStatus.FAILED]
                        ),
                    )
                )
            )
            for reminder in reminders:
                reminder.status = ReminderStatus.CANCELLED
                reminder.last_error = None
            return

        rows = await session.execute(
            select(LessonReminder, CourseReminderStep)
            .join(Enrollment, Enrollment.id == LessonReminder.enrollment_id)
            .join(Lesson, Lesson.id == LessonReminder.lesson_id)
            .join(CourseReminderStep, CourseReminderStep.id == LessonReminder.step_id)
            .outerjoin(
                LessonProgress,
                (LessonProgress.enrollment_id == Enrollment.id)
                & (LessonProgress.lesson_id == Lesson.id),
            )
            .where(
                Enrollment.student_id == student_id,
                Enrollment.status == EnrollmentStatus.ACTIVE,
                Lesson.position == Enrollment.current_lesson_position,
                LessonReminder.status == ReminderStatus.CANCELLED,
                CourseReminderStep.is_active.is_(True),
                or_(LessonProgress.id.is_(None), LessonProgress.viewed_at.is_(None)),
            )
        )
        now = datetime.now(UTC)
        for reminder, step in rows:
            reminder.status = ReminderStatus.PENDING
            reminder.scheduled_at = now + timedelta(hours=step.delay_hours)
            reminder.sent_at = None
            reminder.attempts = 0
            reminder.last_error = None

    async def get_progress(self, telegram_user_id: int) -> ProgressSnapshot | None:
        async with self._session_factory() as session:
            enrollment_row = (
                await session.execute(
                    select(
                        Enrollment.id,
                        Enrollment.current_lesson_position,
                        Course.id.label("course_id"),
                        Course.title,
                    )
                    .join(Student, Enrollment.student_id == Student.id)
                    .join(Cohort, Enrollment.cohort_id == Cohort.id)
                    .join(Course, Cohort.course_id == Course.id)
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()

            if enrollment_row is None:
                return None

            total_lessons = await session.scalar(
                select(func.count(Lesson.id)).where(Lesson.course_id == enrollment_row.course_id)
            )
            total_assignments = await session.scalar(
                select(func.count(Assignment.id))
                .join(Lesson, Assignment.lesson_id == Lesson.id)
                .where(Lesson.course_id == enrollment_row.course_id)
            )
            accepted_submissions = await session.scalar(
                select(func.count(Submission.id)).where(
                    Submission.enrollment_id == enrollment_row.id,
                    Submission.status == SubmissionStatus.ACCEPTED,
                )
            )

            return ProgressSnapshot(
                course_title=enrollment_row.title,
                current_lesson_position=enrollment_row.current_lesson_position,
                total_lessons=total_lessons or 0,
                accepted_submissions=accepted_submissions or 0,
                total_assignments=total_assignments or 0,
            )

    async def get_journey(self, telegram_user_id: int) -> StudentJourney | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Student, Enrollment, Course, Lesson, Assignment, LessonProgress)
                    .outerjoin(Enrollment, Enrollment.student_id == Student.id)
                    .outerjoin(Cohort, Cohort.id == Enrollment.cohort_id)
                    .outerjoin(Course, Course.id == Cohort.course_id)
                    .outerjoin(
                        Lesson,
                        (Lesson.course_id == Course.id)
                        & (Lesson.position == Enrollment.current_lesson_position),
                    )
                    .outerjoin(Assignment, Assignment.lesson_id == Lesson.id)
                    .outerjoin(
                        LessonProgress,
                        (LessonProgress.enrollment_id == Enrollment.id)
                        & (LessonProgress.lesson_id == Lesson.id),
                    )
                    .where(Student.telegram_user_id == telegram_user_id)
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None

            student = row.Student
            enrollment = row.Enrollment
            course = row.Course
            lesson = row.Lesson
            assignment = row.Assignment
            progress = row.LessonProgress

            if enrollment is None or course is None:
                stage = StudentStage.NO_COURSE
            elif enrollment.status is EnrollmentStatus.COMPLETED:
                stage = StudentStage.COURSE_COMPLETED
            elif lesson is None or (
                progress is not None
                and progress.status
                in {LessonProgressStatus.LOCKED, LessonProgressStatus.COMPLETED}
            ):
                stage = StudentStage.LESSON_LOCKED
            else:
                latest_submission_status = None
                if assignment is not None:
                    latest_submission_status = await session.scalar(
                        select(Submission.status)
                        .where(
                            Submission.enrollment_id == enrollment.id,
                            Submission.assignment_id == assignment.id,
                        )
                        .order_by(Submission.attempt_number.desc())
                        .limit(1)
                    )
                if latest_submission_status in {
                    SubmissionStatus.SUBMITTED,
                    SubmissionStatus.IN_REVIEW,
                }:
                    stage = StudentStage.AWAITING_REVIEW
                elif latest_submission_status is SubmissionStatus.REVISION_REQUESTED:
                    stage = StudentStage.REVISION_REQUESTED
                elif progress is None or progress.viewed_at is None:
                    stage = StudentStage.NEEDS_VIEW
                elif assignment is not None:
                    stage = StudentStage.READY_TO_SUBMIT
                else:
                    stage = StudentStage.NEEDS_VIEW

            return StudentJourney(
                stage=stage,
                course_title=course.title if course is not None else None,
                lesson_position=lesson.position if lesson is not None else None,
                lesson_title=lesson.title if lesson is not None else None,
                release_at=progress.release_at if progress is not None else None,
                reminders_enabled=student.reminders_enabled,
                timezone=student.timezone,
                quiet_hours_start=student.quiet_hours_start,
                quiet_hours_end=student.quiet_hours_end,
            )


class StudentAccessError(LookupError):
    """Raised when an admin tries to update an unknown student or cohort."""


class StudentAccessService:
    """Admin use cases for enrollment and access management."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_telegram_students_for_grant(
        self,
        *,
        limit: int = 12,
    ) -> tuple[TelegramCourseGrantStudent, ...]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    Student.id,
                    Student.first_name,
                    Student.last_name,
                    Student.username,
                    Course.title.label("course_title"),
                    Enrollment.current_lesson_position,
                )
                .outerjoin(Enrollment, Enrollment.student_id == Student.id)
                .outerjoin(Cohort, Cohort.id == Enrollment.cohort_id)
                .outerjoin(Course, Course.id == Cohort.course_id)
                .where(
                    Student.origin == StudentOrigin.TELEGRAM,
                    Student.telegram_user_id.is_not(None),
                    Student.is_active.is_(True),
                )
                .order_by(Student.created_at.desc(), Enrollment.created_at.desc())
                .limit(limit)
            )
            result: list[TelegramCourseGrantStudent] = []
            seen: set[UUID] = set()
            for row in rows:
                if row.id in seen:
                    continue
                seen.add(row.id)
                name = " ".join(
                    item for item in (row.first_name, row.last_name) if item
                ).strip()
                result.append(
                    TelegramCourseGrantStudent(
                        student_id=row.id,
                        name=name or row.username or "Telegram ученик",
                        username=row.username,
                        course_title=row.course_title,
                        current_lesson_position=row.current_lesson_position,
                    )
                )
            return tuple(result)

    async def list_telegram_courses_for_grant(
        self,
        *,
        limit: int = 12,
    ) -> tuple[TelegramCourseGrantCourse, ...]:
        lessons_count = (
            select(func.count(Lesson.id))
            .where(Lesson.course_id == Course.id, Lesson.is_published.is_(True))
            .correlate(Course)
            .scalar_subquery()
        )
        students_count = (
            select(func.count(func.distinct(Enrollment.student_id)))
            .join(Cohort, Cohort.id == Enrollment.cohort_id)
            .where(Cohort.course_id == Course.id)
            .correlate(Course)
            .scalar_subquery()
        )
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    Course.id,
                    Course.title,
                    lessons_count.label("lessons_count"),
                    students_count.label("students_count"),
                )
                .where(
                    Course.audience == CourseAudience.TELEGRAM,
                    Course.is_active.is_(True),
                )
                .order_by(Course.created_at.desc())
                .limit(limit)
            )
            return tuple(
                TelegramCourseGrantCourse(
                    course_id=row.id,
                    title=row.title,
                    lessons_count=row.lessons_count or 0,
                    students_count=row.students_count or 0,
                )
                for row in rows
            )

    async def grant_telegram_course(
        self,
        *,
        student_id: UUID,
        course_id: UUID,
        access_type: AccessType = AccessType.MANUAL,
    ) -> Any:
        async with session_scope(self._session_factory) as session:
            student = await session.get(Student, student_id)
            course = await session.get(Course, course_id)
            if student is None or student.origin is not StudentOrigin.TELEGRAM:
                raise StudentAccessError("telegram-student-not-found")
            if course is None or course.audience is not CourseAudience.TELEGRAM:
                raise StudentAccessError("telegram-course-not-found")
            cohort = await session.scalar(
                select(Cohort)
                .where(Cohort.course_id == course.id, Cohort.is_active.is_(True))
                .order_by(Cohort.created_at)
                .limit(1)
            )
            if cohort is None:
                cohort = Cohort(
                    course_id=course.id,
                    title="Основной поток",
                    is_active=True,
                )
                session.add(cohort)
                await session.flush()
            cohort_id = cohort.id

        return await self.update_enrollment(
            student_id=student_id,
            cohort_id=cohort_id,
            status=EnrollmentStatus.ACTIVE,
            access_type=access_type,
            current_lesson_position=1,
        )

    async def assign_discord_course(self, *, student_id: UUID, course_id: UUID) -> Any:
        async with session_scope(self._session_factory) as session:
            student = await session.get(Student, student_id)
            course = await session.get(Course, course_id)
            if student is None or student.origin is not StudentOrigin.DISCORD:
                raise StudentAccessError("discord-participant-not-found")
            if course is None or course.audience is not CourseAudience.DISCORD:
                raise StudentAccessError("discord-course-not-found")
            cohort = await session.scalar(
                select(Cohort)
                .where(Cohort.course_id == course.id, Cohort.is_active.is_(True))
                .order_by(Cohort.created_at)
                .limit(1)
            )
            if cohort is None:
                cohort = Cohort(
                    course_id=course.id,
                    title="Основной поток",
                    is_active=True,
                )
                session.add(cohort)
                await session.flush()
            enrollment = await session.scalar(
                select(Enrollment)
                .where(Enrollment.student_id == student.id)
                .order_by(Enrollment.created_at.desc())
                .limit(1)
            )
            if enrollment is None:
                enrollment = Enrollment(student_id=student.id, cohort_id=cohort.id)
                session.add(enrollment)
            else:
                enrollment.cohort_id = cohort.id
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.access_type = AccessType.MANUAL
            enrollment.current_lesson_position = 1
            student.is_active = True
        return await self.update_enrollment(
            student_id=student_id,
            cohort_id=cohort.id,
            status=EnrollmentStatus.ACTIVE,
            access_type=AccessType.MANUAL,
            current_lesson_position=1,
        )

    async def revoke_discord_access(self, *, student_id: UUID) -> None:
        async with session_scope(self._session_factory) as session:
            student = await session.get(Student, student_id)
            if student is None or student.origin is not StudentOrigin.DISCORD:
                raise StudentAccessError("discord-participant-not-found")
            enrollment = await session.scalar(
                select(Enrollment)
                .where(Enrollment.student_id == student.id)
                .order_by(Enrollment.created_at.desc())
                .limit(1)
            )
            if enrollment is not None:
                enrollment.status = EnrollmentStatus.REVOKED

    async def update_enrollment(
        self,
        *,
        student_id: UUID,
        cohort_id: UUID,
        status: EnrollmentStatus,
        access_type: AccessType,
        current_lesson_position: int | None = None,
    ) -> Any:
        from course_platform.services.admin_dashboard import AdminDashboardService

        async with session_scope(self._session_factory) as session:
            student = await session.get(Student, student_id)
            if student is None:
                raise StudentAccessError("student-not-found")

            cohort = await session.get(Cohort, cohort_id)
            if cohort is None:
                raise StudentAccessError("cohort-not-found")
            course = await session.get(Course, cohort.course_id)
            if course is None:
                raise StudentAccessError("course-not-found")
            expected_audience = (
                CourseAudience.DISCORD
                if student.origin is StudentOrigin.DISCORD
                else CourseAudience.TELEGRAM
            )
            if course.audience is not expected_audience:
                raise StudentAccessError("course-audience-mismatch")

            enrollment = await session.scalar(
                select(Enrollment)
                .where(Enrollment.student_id == student_id)
                .order_by(Enrollment.created_at.desc())
                .limit(1)
            )

            if enrollment is None:
                should_notify_access = True
                enrollment = Enrollment(
                    student_id=student.id,
                    cohort_id=cohort.id,
                    status=status,
                    access_type=access_type,
                    current_lesson_position=current_lesson_position or 1,
                )
                session.add(enrollment)
            else:
                should_notify_access = (
                    enrollment.cohort_id != cohort.id
                    or enrollment.status is not EnrollmentStatus.ACTIVE
                )
                enrollment.cohort_id = cohort.id
                enrollment.status = status
                enrollment.access_type = access_type
                if current_lesson_position is not None:
                    enrollment.current_lesson_position = current_lesson_position
            if (
                should_notify_access
                and status is EnrollmentStatus.ACTIVE
                and student.origin is StudentOrigin.TELEGRAM
            ):
                enrollment.access_notified_at = None

        dashboard = AdminDashboardService(self._session_factory)
        detail: Any = await dashboard.get_student_detail(
            student_id=student_id,
            enrollment_id=enrollment.id,
        )
        return detail
