"""Read-only data projections for the curator web interface."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    CourseReminderStep,
    Enrollment,
    Feedback,
    Lesson,
    LessonProgress,
    LessonReminder,
    StaffUser,
    Student,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import (
    AccessType,
    CourseAudience,
    EnrollmentStatus,
    FeedbackVerdict,
    LessonProgressStatus,
    ReminderKind,
    ReminderStatus,
    StudentOrigin,
    SubmissionKind,
    SubmissionSource,
    SubmissionStatus,
    UnlockRule,
    VideoSource,
)
from course_platform.services.access_scope import StaffScope
from course_platform.services.reviews import ReviewAttachment, _review_attachment


class StudentNotFoundError(RuntimeError):
    pass


class StudentLessonNotFoundError(RuntimeError):
    pass


class CuratorNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    pending_reviews: int
    active_students: int
    completed_enrollments: int
    active_courses: int
    average_progress_percent: int


@dataclass(frozen=True, slots=True)
class StudentOverview:
    student_id: UUID
    enrollment_id: UUID | None
    course_id: UUID | None
    cohort_id: UUID | None
    name: str
    username: str | None
    is_active: bool
    course_title: str | None
    cohort_title: str | None
    enrollment_status: EnrollmentStatus | None
    access_type: AccessType | None
    current_lesson_position: int | None
    total_lessons: int
    accepted_submissions: int
    total_assignments: int
    progress_percent: int
    assigned_curator_id: UUID | None
    assigned_curator_name: str | None


@dataclass(frozen=True, slots=True)
class StudentLessonProgress:
    lesson_id: UUID
    position: int
    title: str
    status: LessonProgressStatus
    release_at: datetime | None
    available_at: datetime | None
    viewed_at: datetime | None
    homework_submitted_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class StudentSubmissionHistory:
    submission_id: UUID
    lesson_position: int
    lesson_title: str
    attempt_number: int
    status: SubmissionStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    attachment_count: int
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None
    attachments: tuple[ReviewAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class StudentDetail(StudentOverview):
    telegram_user_id: int
    language_code: str | None
    registered_at: datetime
    enrolled_at: datetime | None
    access_type: AccessType | None
    total_attempts: int
    pending_submissions: int
    revision_requests: int
    last_activity_at: datetime
    timezone: str
    quiet_hours_start: int
    quiet_hours_end: int
    reminders_enabled: bool
    next_reminder_at: datetime | None
    next_reminder_kind: ReminderKind | None
    requires_attention: bool
    lesson_progress: tuple[StudentLessonProgress, ...]
    recent_submissions: tuple[StudentSubmissionHistory, ...]


@dataclass(frozen=True, slots=True)
class StudentLessonAttempt:
    submission_id: UUID
    attempt_number: int
    status: SubmissionStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    text_body: str | None
    attachment_count: int
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None


@dataclass(frozen=True, slots=True)
class StudentLessonDetail:
    student_id: UUID
    enrollment_id: UUID
    lesson_id: UUID
    position: int
    title: str
    description: str | None
    video_source: VideoSource
    video_reference: str | None
    release_offset_hours: int
    requires_view_confirmation: bool
    is_published: bool
    status: LessonProgressStatus
    release_at: datetime | None
    available_at: datetime | None
    viewed_at: datetime | None
    homework_submitted_at: datetime | None
    completed_at: datetime | None
    assignment_instructions: str | None
    submission_kind: SubmissionKind | None
    assignment_is_required: bool | None
    attempts: tuple[StudentLessonAttempt, ...]


@dataclass(frozen=True, slots=True)
class CourseOverview:
    course_id: UUID
    slug: str
    title: str
    description: str | None
    audience: CourseAudience
    unlock_rule: UnlockRule
    is_active: bool
    lessons_count: int
    cohorts_count: int
    students_count: int


class AdminDashboardService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_student_lesson_detail(
        self,
        *,
        student_id: UUID,
        enrollment_id: UUID,
        lesson_id: UUID,
        viewer: StaffScope | None = None,
    ) -> StudentLessonDetail:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Student, Enrollment, Lesson, LessonProgress, Assignment)
                    .join(Enrollment, Enrollment.student_id == Student.id)
                    .join(Cohort, Cohort.id == Enrollment.cohort_id)
                    .join(Lesson, Lesson.course_id == Cohort.course_id)
                    .outerjoin(
                        LessonProgress,
                        (LessonProgress.enrollment_id == Enrollment.id)
                        & (LessonProgress.lesson_id == Lesson.id),
                    )
                    .outerjoin(Assignment, Assignment.lesson_id == Lesson.id)
                    .where(
                        Student.id == student_id,
                        Enrollment.id == enrollment_id,
                        Lesson.id == lesson_id,
                    )
                )
            ).one_or_none()
            if row is None:
                raise StudentLessonNotFoundError

            student, enrollment, lesson, progress, assignment = row
            if (
                viewer is not None
                and not viewer.is_admin
                and student.assigned_curator_id not in (None, viewer.staff_id)
            ):
                raise StudentLessonNotFoundError
            fallback_status = (
                LessonProgressStatus.COMPLETED
                if lesson.position < enrollment.current_lesson_position
                else LessonProgressStatus.AVAILABLE
                if lesson.position == enrollment.current_lesson_position
                else LessonProgressStatus.LOCKED
            )
            attachment_count = (
                select(func.count())
                .select_from(SubmissionAttachment)
                .where(SubmissionAttachment.submission_id == Submission.id)
                .correlate(Submission)
                .scalar_subquery()
            )
            attempts: list[StudentLessonAttempt] = []
            if assignment is not None:
                attempt_rows = await session.execute(
                    select(
                        Submission,
                        Feedback.verdict,
                        Feedback.message,
                        attachment_count.label("attachment_count"),
                    )
                    .outerjoin(Feedback, Feedback.submission_id == Submission.id)
                    .where(
                        Submission.enrollment_id == enrollment.id,
                        Submission.assignment_id == assignment.id,
                    )
                    .order_by(Submission.attempt_number.desc())
                )
                attempts = [
                    StudentLessonAttempt(
                        submission_id=attempt.Submission.id,
                        attempt_number=attempt.Submission.attempt_number,
                        status=attempt.Submission.status,
                        submitted_at=attempt.Submission.submitted_at,
                        reviewed_at=attempt.Submission.reviewed_at,
                        text_body=attempt.Submission.text_body,
                        attachment_count=attempt.attachment_count,
                        feedback_verdict=attempt.verdict,
                        feedback_message=attempt.message,
                    )
                    for attempt in attempt_rows
                ]

            return StudentLessonDetail(
                student_id=student.id,
                enrollment_id=enrollment.id,
                lesson_id=lesson.id,
                position=lesson.position,
                title=lesson.title,
                description=lesson.description,
                video_source=lesson.video_source,
                video_reference=lesson.video_reference,
                release_offset_hours=lesson.release_offset_hours,
                requires_view_confirmation=lesson.requires_view_confirmation,
                is_published=lesson.is_published,
                status=progress.status if progress is not None else fallback_status,
                release_at=progress.release_at if progress is not None else None,
                available_at=progress.available_at if progress is not None else None,
                viewed_at=progress.viewed_at if progress is not None else None,
                homework_submitted_at=(
                    progress.homework_submitted_at if progress is not None else None
                ),
                completed_at=progress.completed_at if progress is not None else None,
                assignment_instructions=(
                    assignment.instructions if assignment is not None else None
                ),
                submission_kind=(
                    assignment.submission_kind if assignment is not None else None
                ),
                assignment_is_required=(
                    assignment.is_required if assignment is not None else None
                ),
                attempts=tuple(attempts),
            )

    async def summary(self, *, viewer: StaffScope | None = None) -> DashboardSummary:
        students = await self.list_students(viewer=viewer)
        enrolled_progress = [
            student.progress_percent
            for student in students
            if student.enrollment_id is not None
        ]
        async with self._session_factory() as session:
            pending_query = (
                select(func.count(Submission.id))
                .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                .join(Student, Student.id == Enrollment.student_id)
                .where(
                    Submission.source == SubmissionSource.TELEGRAM,
                    Submission.status.in_(
                        [SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW]
                    ),
                )
            )
            if viewer is not None and not viewer.is_admin:
                pending_query = pending_query.where(
                    or_(
                        Student.assigned_curator_id.is_(None),
                        Student.assigned_curator_id == viewer.staff_id,
                    )
                )
            pending_reviews = await session.scalar(pending_query)
            active_courses = await session.scalar(
                select(func.count(Course.id)).where(
                    Course.is_active.is_(True),
                    Course.audience == CourseAudience.TELEGRAM,
                )
            )

        average_progress = (
            round(sum(enrolled_progress) / len(enrolled_progress))
            if enrolled_progress
            else 0
        )
        return DashboardSummary(
            pending_reviews=pending_reviews or 0,
            active_students=sum(1 for student in students if student.is_active),
            completed_enrollments=sum(
                1
                for student in students
                if student.enrollment_status == EnrollmentStatus.COMPLETED
            ),
            active_courses=active_courses or 0,
            average_progress_percent=average_progress,
        )

    async def list_students(
        self,
        *,
        viewer: StaffScope | None = None,
    ) -> list[StudentOverview]:
        async with self._session_factory() as session:
            staff_telegram_ids = set(
                await session.scalars(
                    select(StaffUser.telegram_user_id).where(
                        StaffUser.telegram_user_id.is_not(None)
                    )
                )
            )
            curator = aliased(StaffUser)
            query = (
                select(
                    Student.id.label("student_id"),
                    Student.telegram_user_id,
                    Student.first_name,
                    Student.last_name,
                    Student.username,
                    Student.is_active,
                    Student.assigned_curator_id,
                    curator.display_name.label("assigned_curator_name"),
                    Enrollment.id.label("enrollment_id"),
                    Enrollment.cohort_id.label("cohort_id"),
                    Enrollment.access_type.label("access_type"),
                    Enrollment.status.label("enrollment_status"),
                    Enrollment.current_lesson_position,
                    Course.id.label("course_id"),
                    Course.title.label("course_title"),
                    Cohort.title.label("cohort_title"),
                )
                .outerjoin(Enrollment, Enrollment.student_id == Student.id)
                .outerjoin(Cohort, Cohort.id == Enrollment.cohort_id)
                .outerjoin(Course, Course.id == Cohort.course_id)
                .outerjoin(curator, curator.id == Student.assigned_curator_id)
                .where(Student.origin == StudentOrigin.TELEGRAM)
                .order_by(Student.created_at.desc(), Enrollment.created_at.desc())
            )
            if viewer is not None and not viewer.is_admin:
                query = query.where(
                    or_(
                        Student.assigned_curator_id.is_(None),
                        Student.assigned_curator_id == viewer.staff_id,
                    )
                )
            rows = await session.execute(query)

            result: list[StudentOverview] = []
            for row in rows:
                if row.telegram_user_id in staff_telegram_ids and row.enrollment_id is None:
                    continue
                total_lessons = 0
                total_assignments = 0
                accepted_submissions = 0
                if row.course_id is not None:
                    total_lessons = (
                        await session.scalar(
                            select(func.count(Lesson.id)).where(
                                Lesson.course_id == row.course_id
                            )
                        )
                        or 0
                    )
                    total_assignments = (
                        await session.scalar(
                            select(func.count(Assignment.id))
                            .join(Lesson, Lesson.id == Assignment.lesson_id)
                            .where(Lesson.course_id == row.course_id)
                        )
                        or 0
                    )
                if row.enrollment_id is not None:
                    accepted_submissions = (
                        await session.scalar(
                            select(func.count(distinct(Submission.assignment_id))).where(
                                Submission.enrollment_id == row.enrollment_id,
                                Submission.status == SubmissionStatus.ACCEPTED,
                            )
                        )
                        or 0
                    )
                progress = (
                    round(accepted_submissions / total_assignments * 100)
                    if total_assignments
                    else 0
                )
                result.append(
                    StudentOverview(
                        student_id=row.student_id,
                        enrollment_id=row.enrollment_id,
                        course_id=row.course_id,
                        cohort_id=row.cohort_id,
                        name=" ".join(
                            part for part in [row.first_name, row.last_name] if part
                        ),
                        username=row.username,
                        is_active=row.is_active,
                        course_title=row.course_title,
                        cohort_title=row.cohort_title,
                        enrollment_status=row.enrollment_status,
                        access_type=row.access_type,
                        current_lesson_position=row.current_lesson_position,
                        total_lessons=total_lessons,
                        accepted_submissions=accepted_submissions,
                        total_assignments=total_assignments,
                        progress_percent=progress,
                        assigned_curator_id=row.assigned_curator_id,
                        assigned_curator_name=row.assigned_curator_name,
                    )
                )
            return result

    async def assign_curator(
        self,
        *,
        student_id: UUID,
        curator_id: UUID | None,
    ) -> StudentDetail:
        async with session_scope(self._session_factory) as session:
            student = await session.get(Student, student_id)
            if student is None or student.origin is not StudentOrigin.TELEGRAM:
                raise StudentNotFoundError
            if curator_id is not None:
                curator = await session.get(StaffUser, curator_id)
                if curator is None or not curator.is_active:
                    raise CuratorNotFoundError
            student.assigned_curator_id = curator_id
        return await self.get_student_detail(student_id=student_id)

    async def get_student_detail(
        self,
        *,
        student_id: UUID,
        enrollment_id: UUID | None = None,
        viewer: StaffScope | None = None,
    ) -> StudentDetail:
        async with self._session_factory() as session:
            curator = aliased(StaffUser)
            row = (
                await session.execute(
                    select(
                        Student,
                        Enrollment,
                        Cohort.id.label("cohort_id"),
                        Course.id.label("course_id"),
                        Course.title.label("course_title"),
                        Cohort.title.label("cohort_title"),
                        curator.display_name.label("assigned_curator_name"),
                    )
                    .outerjoin(Enrollment, Enrollment.student_id == Student.id)
                    .outerjoin(Cohort, Cohort.id == Enrollment.cohort_id)
                    .outerjoin(Course, Course.id == Cohort.course_id)
                    .outerjoin(curator, curator.id == Student.assigned_curator_id)
                    .where(
                        Student.id == student_id,
                        *(
                            [Enrollment.id == enrollment_id]
                            if enrollment_id is not None
                            else []
                        ),
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                raise StudentNotFoundError

            student = row.Student
            enrollment = row.Enrollment
            if (
                viewer is not None
                and not viewer.is_admin
                and student.assigned_curator_id not in (None, viewer.staff_id)
            ):
                raise StudentNotFoundError
            total_lessons = 0
            total_assignments = 0
            accepted_submissions = 0
            total_attempts = 0
            pending_submissions = 0
            revision_requests = 0
            lesson_progress: list[StudentLessonProgress] = []
            recent_submissions: list[StudentSubmissionHistory] = []
            last_activity_at = student.last_activity_at
            next_reminder_at: datetime | None = None
            next_reminder_kind: ReminderKind | None = None
            requires_attention = False

            if enrollment is not None and row.course_id is not None:
                total_lessons = (
                    await session.scalar(
                        select(func.count(Lesson.id)).where(
                            Lesson.course_id == row.course_id,
                            Lesson.is_published.is_(True),
                        )
                    )
                    or 0
                )
                total_assignments = (
                    await session.scalar(
                        select(func.count(Assignment.id))
                        .join(Lesson, Assignment.lesson_id == Lesson.id)
                        .where(Lesson.course_id == row.course_id)
                    )
                    or 0
                )
                accepted_submissions = (
                    await session.scalar(
                        select(func.count(distinct(Submission.assignment_id))).where(
                            Submission.enrollment_id == enrollment.id,
                            Submission.status == SubmissionStatus.ACCEPTED,
                        )
                    )
                    or 0
                )
                status_rows = await session.execute(
                    select(Submission.status, func.count(Submission.id))
                    .where(Submission.enrollment_id == enrollment.id)
                    .group_by(Submission.status)
                )
                status_counts = {status_value: count for status_value, count in status_rows}
                total_attempts = sum(status_counts.values())
                pending_submissions = sum(
                    status_counts.get(status_value, 0)
                    for status_value in (
                        SubmissionStatus.SUBMITTED,
                        SubmissionStatus.IN_REVIEW,
                    )
                )
                revision_requests = status_counts.get(
                    SubmissionStatus.REVISION_REQUESTED,
                    0,
                )

                progress_rows = await session.execute(
                    select(Lesson, LessonProgress)
                    .outerjoin(
                        LessonProgress,
                        (LessonProgress.lesson_id == Lesson.id)
                        & (LessonProgress.enrollment_id == enrollment.id),
                    )
                    .where(
                        Lesson.course_id == row.course_id,
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Lesson.position)
                )
                for lesson, progress in progress_rows:
                    fallback_status = (
                        LessonProgressStatus.COMPLETED
                        if lesson.position < enrollment.current_lesson_position
                        else LessonProgressStatus.AVAILABLE
                        if lesson.position == enrollment.current_lesson_position
                        else LessonProgressStatus.LOCKED
                    )
                    lesson_progress.append(
                        StudentLessonProgress(
                            lesson_id=lesson.id,
                            position=lesson.position,
                            title=lesson.title,
                            status=progress.status if progress is not None else fallback_status,
                            release_at=progress.release_at if progress is not None else None,
                            available_at=progress.available_at if progress is not None else None,
                            viewed_at=progress.viewed_at if progress is not None else None,
                            homework_submitted_at=(
                                progress.homework_submitted_at
                                if progress is not None
                                else None
                            ),
                            completed_at=progress.completed_at if progress is not None else None,
                        )
                    )
                    if progress is not None and progress.updated_at > last_activity_at:
                        last_activity_at = progress.updated_at

                attachment_count = (
                    select(func.count())
                    .select_from(SubmissionAttachment)
                    .where(SubmissionAttachment.submission_id == Submission.id)
                    .correlate(Submission)
                    .scalar_subquery()
                )
                history_rows = await session.execute(
                    select(
                        Submission,
                        Lesson.position,
                        Lesson.title,
                        Feedback.verdict,
                        Feedback.message,
                        attachment_count.label("attachment_count"),
                    )
                    .join(Assignment, Assignment.id == Submission.assignment_id)
                    .join(Lesson, Lesson.id == Assignment.lesson_id)
                    .outerjoin(Feedback, Feedback.submission_id == Submission.id)
                    .where(Submission.enrollment_id == enrollment.id)
                    .order_by(Submission.submitted_at.desc())
                    .limit(20)
                )
                history_entries = list(history_rows)
                attachments_by_submission: dict[UUID, list[SubmissionAttachment]] = {}
                submission_ids = [entry.Submission.id for entry in history_entries]
                if submission_ids:
                    attachment_rows = await session.scalars(
                        select(SubmissionAttachment)
                        .where(SubmissionAttachment.submission_id.in_(submission_ids))
                        .order_by(SubmissionAttachment.created_at)
                    )
                    for attachment in attachment_rows:
                        attachments_by_submission.setdefault(
                            attachment.submission_id, []
                        ).append(attachment)
                for history in history_entries:
                    recent_submissions.append(
                        StudentSubmissionHistory(
                            submission_id=history.Submission.id,
                            lesson_position=history.position,
                            lesson_title=history.title,
                            attempt_number=history.Submission.attempt_number,
                            status=history.Submission.status,
                            submitted_at=history.Submission.submitted_at,
                            reviewed_at=history.Submission.reviewed_at,
                            attachment_count=history.attachment_count,
                            feedback_verdict=history.verdict,
                            feedback_message=history.message,
                            attachments=tuple(
                                _review_attachment(attachment)
                                for attachment in attachments_by_submission.get(
                                    history.Submission.id, []
                                )
                            ),
                        )
                    )
                    if history.Submission.submitted_at > last_activity_at:
                        last_activity_at = history.Submission.submitted_at

                next_reminder = (
                    await session.execute(
                        select(LessonReminder.scheduled_at, CourseReminderStep.kind)
                        .join(
                            CourseReminderStep,
                            CourseReminderStep.id == LessonReminder.step_id,
                        )
                        .where(
                            LessonReminder.enrollment_id == enrollment.id,
                            LessonReminder.status.in_(
                                [ReminderStatus.PENDING, ReminderStatus.FAILED]
                            ),
                        )
                        .order_by(LessonReminder.scheduled_at)
                        .limit(1)
                    )
                ).one_or_none()
                if next_reminder is not None:
                    next_reminder_at = next_reminder.scheduled_at
                    next_reminder_kind = next_reminder.kind
                requires_attention = (
                    await session.scalar(
                        select(func.count(LessonReminder.id))
                        .join(
                            CourseReminderStep,
                            CourseReminderStep.id == LessonReminder.step_id,
                        )
                        .where(
                            LessonReminder.enrollment_id == enrollment.id,
                            LessonReminder.status == ReminderStatus.SENT,
                            CourseReminderStep.kind == ReminderKind.CURATOR_ALERT,
                        )
                    )
                    or 0
                ) > 0

            progress_percent = (
                round(accepted_submissions / total_assignments * 100)
                if total_assignments
                else 0
            )
            return StudentDetail(
                student_id=student.id,
                enrollment_id=enrollment.id if enrollment is not None else None,
                course_id=row.course_id,
                cohort_id=row.cohort_id,
                name=" ".join(
                    part for part in [student.first_name, student.last_name] if part
                ),
                username=student.username,
                is_active=student.is_active,
                course_title=row.course_title,
                cohort_title=row.cohort_title,
                enrollment_status=enrollment.status if enrollment is not None else None,
                access_type=enrollment.access_type if enrollment is not None else None,
                current_lesson_position=(
                    enrollment.current_lesson_position if enrollment is not None else None
                ),
                total_lessons=total_lessons,
                accepted_submissions=accepted_submissions,
                total_assignments=total_assignments,
                progress_percent=progress_percent,
                assigned_curator_id=student.assigned_curator_id,
                assigned_curator_name=row.assigned_curator_name,
                telegram_user_id=student.telegram_user_id,
                language_code=student.language_code,
                registered_at=student.created_at,
                enrolled_at=enrollment.created_at if enrollment is not None else None,
                total_attempts=total_attempts,
                pending_submissions=pending_submissions,
                revision_requests=revision_requests,
                last_activity_at=last_activity_at,
                timezone=student.timezone,
                quiet_hours_start=student.quiet_hours_start,
                quiet_hours_end=student.quiet_hours_end,
                reminders_enabled=student.reminders_enabled,
                next_reminder_at=next_reminder_at,
                next_reminder_kind=next_reminder_kind,
                requires_attention=requires_attention,
                lesson_progress=tuple(lesson_progress),
                recent_submissions=tuple(recent_submissions),
            )

    async def list_courses(self) -> list[CourseOverview]:
        lesson_count = (
            select(func.count(Lesson.id))
            .where(Lesson.course_id == Course.id)
            .correlate(Course)
            .scalar_subquery()
        )
        cohort_count = (
            select(func.count(Cohort.id))
            .where(Cohort.course_id == Course.id)
            .correlate(Course)
            .scalar_subquery()
        )
        student_count = (
            select(func.count(distinct(Enrollment.student_id)))
            .join(Cohort, Cohort.id == Enrollment.cohort_id)
            .where(Cohort.course_id == Course.id)
            .correlate(Course)
            .scalar_subquery()
        )
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    Course.id,
                    Course.slug,
                    Course.title,
                    Course.description,
                    Course.audience,
                    Course.unlock_rule,
                    Course.is_active,
                    lesson_count.label("lessons_count"),
                    cohort_count.label("cohorts_count"),
                    student_count.label("students_count"),
                ).order_by(Course.created_at.desc())
            )
            return [
                CourseOverview(
                    course_id=row.id,
                    slug=row.slug,
                    title=row.title,
                    description=row.description,
                    audience=row.audience,
                    unlock_rule=row.unlock_rule,
                    is_active=row.is_active,
                    lessons_count=row.lessons_count,
                    cohorts_count=row.cohorts_count,
                    students_count=row.students_count,
                )
                for row in rows
            ]
