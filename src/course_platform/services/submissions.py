"""Explicit, persistent homework submission workflow."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Feedback,
    Lesson,
    LessonProgress,
    Student,
    StudentBotState,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import (
    AttachmentKind,
    ConversationState,
    EnrollmentStatus,
    LessonProgressStatus,
    SubmissionKind,
    SubmissionStatus,
)
from course_platform.services.progression import ProgressionService


class SubmissionWorkflowError(RuntimeError):
    """Base class for expected submission workflow outcomes."""


class NoActiveAssignmentError(SubmissionWorkflowError):
    pass


class SubmissionPendingError(SubmissionWorkflowError):
    pass


class AssignmentAcceptedError(SubmissionWorkflowError):
    pass


class UnsupportedSubmissionKindError(SubmissionWorkflowError):
    pass


class NotAwaitingSubmissionError(SubmissionWorkflowError):
    pass


class EmptySubmissionError(SubmissionWorkflowError):
    pass


class LessonNotViewedError(SubmissionWorkflowError):
    pass


@dataclass(frozen=True, slots=True)
class SubmissionPrompt:
    lesson_position: int
    lesson_title: str
    instructions: str
    submission_kind: SubmissionKind


@dataclass(frozen=True, slots=True)
class SubmissionReceipt:
    lesson_position: int
    lesson_title: str
    attempt_number: int


@dataclass(frozen=True, slots=True)
class HomeworkAttachment:
    kind: AttachmentKind
    telegram_file_id: str
    telegram_file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class StudentJournalEntry:
    lesson_position: int
    lesson_title: str
    attempt_number: int
    status: SubmissionStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    feedback_message: str | None


class SubmissionService:
    """Start and complete submissions for the current unlocked lesson."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def journal(
        self, telegram_user_id: int, *, limit: int = 10
    ) -> tuple[StudentJournalEntry, ...]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(Submission, Lesson.position, Lesson.title, Feedback.message)
                .join(Enrollment, Enrollment.id == Submission.enrollment_id)
                .join(Student, Student.id == Enrollment.student_id)
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .join(Lesson, Lesson.id == Assignment.lesson_id)
                .outerjoin(Feedback, Feedback.submission_id == Submission.id)
                .where(Student.telegram_user_id == telegram_user_id)
                .order_by(Submission.submitted_at.desc())
                .limit(limit)
            )
            return tuple(
                StudentJournalEntry(
                    lesson_position=row.position,
                    lesson_title=row.title,
                    attempt_number=row.Submission.attempt_number,
                    status=row.Submission.status,
                    submitted_at=row.Submission.submitted_at,
                    reviewed_at=row.Submission.reviewed_at,
                    feedback_message=row.message,
                )
                for row in rows
            )

    async def begin(self, telegram_user_id: int) -> SubmissionPrompt:
        async with session_scope(self._session_factory) as session:
            row = (
                await session.execute(
                    select(
                        Student.id.label("student_id"),
                        Enrollment.id.label("enrollment_id"),
                        Lesson.id.label("lesson_id"),
                        Lesson.position,
                        Lesson.title,
                        Lesson.requires_view_confirmation,
                        Assignment.id.label("assignment_id"),
                        Assignment.instructions,
                        Assignment.submission_kind,
                    )
                    .join(Enrollment, Enrollment.student_id == Student.id)
                    .join(Cohort, Cohort.id == Enrollment.cohort_id)
                    .join(Course, Course.id == Cohort.course_id)
                    .join(
                        Lesson,
                        (Lesson.course_id == Course.id)
                        & (Lesson.position == Enrollment.current_lesson_position),
                    )
                    .join(Assignment, Assignment.lesson_id == Lesson.id)
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Student.is_active.is_(True),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Course.is_active.is_(True),
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()

            if row is None:
                raise NoActiveAssignmentError

            latest_status = await session.scalar(
                select(Submission.status)
                .where(
                    Submission.enrollment_id == row.enrollment_id,
                    Submission.assignment_id == row.assignment_id,
                )
                .order_by(Submission.attempt_number.desc())
                .limit(1)
            )
            if latest_status is SubmissionStatus.ACCEPTED:
                raise AssignmentAcceptedError
            if latest_status in {SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW}:
                raise SubmissionPendingError
            if (
                row.requires_view_confirmation
                and latest_status is not SubmissionStatus.REVISION_REQUESTED
            ):
                progress_status = await session.scalar(
                    select(LessonProgress.status).where(
                        LessonProgress.enrollment_id == row.enrollment_id,
                        LessonProgress.lesson_id == row.lesson_id,
                    )
                )
                if progress_status not in {
                    LessonProgressStatus.VIEWED,
                    LessonProgressStatus.HOMEWORK_SUBMITTED,
                    LessonProgressStatus.COMPLETED,
                }:
                    raise LessonNotViewedError

            bot_state = await session.get(StudentBotState, row.student_id)
            if bot_state is None:
                bot_state = StudentBotState(student_id=row.student_id)
                session.add(bot_state)
            bot_state.state = ConversationState.AWAITING_HOMEWORK
            bot_state.assignment_id = row.assignment_id

            return SubmissionPrompt(
                lesson_position=row.position,
                lesson_title=row.title,
                instructions=row.instructions,
                submission_kind=row.submission_kind,
            )

    async def submit_text(self, telegram_user_id: int, text: str) -> SubmissionReceipt:
        normalized_text = text.strip()
        if not normalized_text:
            raise EmptySubmissionError

        async with session_scope(self._session_factory) as session:
            row = await self._get_waiting_context(session, telegram_user_id)
            if row.submission_kind not in {SubmissionKind.TEXT, SubmissionKind.ANY}:
                raise UnsupportedSubmissionKindError

            attempt_number = await self._next_attempt_number(session, row)
            session.add(
                Submission(
                    enrollment_id=row.enrollment_id,
                    assignment_id=row.assignment_id,
                    attempt_number=attempt_number,
                    text_body=normalized_text,
                    status=SubmissionStatus.SUBMITTED,
                )
            )
            await ProgressionService.record_submission(
                session,
                enrollment_id=row.enrollment_id,
                lesson_id=row.lesson_id,
            )
            self._clear_waiting_state(row)

            return self._receipt(row, attempt_number)

    async def submit_attachment(
        self,
        telegram_user_id: int,
        attachment: HomeworkAttachment,
        *,
        caption: str | None = None,
    ) -> SubmissionReceipt:
        async with session_scope(self._session_factory) as session:
            row = await self._get_waiting_context(session, telegram_user_id)
            allowed_kinds = {
                AttachmentKind.DOCUMENT: {SubmissionKind.FILE, SubmissionKind.ANY},
                AttachmentKind.PHOTO: {SubmissionKind.PHOTO, SubmissionKind.ANY},
                AttachmentKind.VIDEO: {SubmissionKind.VIDEO, SubmissionKind.ANY},
                AttachmentKind.VIDEO_NOTE: {SubmissionKind.VIDEO, SubmissionKind.ANY},
            }
            if row.submission_kind not in allowed_kinds[attachment.kind]:
                raise UnsupportedSubmissionKindError

            attempt_number = await self._next_attempt_number(session, row)
            normalized_caption = caption.strip() if caption and caption.strip() else None
            submission = Submission(
                enrollment_id=row.enrollment_id,
                assignment_id=row.assignment_id,
                attempt_number=attempt_number,
                text_body=normalized_caption,
                status=SubmissionStatus.SUBMITTED,
            )
            submission.attachments.append(
                SubmissionAttachment(
                    kind=attachment.kind,
                    telegram_file_id=attachment.telegram_file_id,
                    telegram_file_unique_id=attachment.telegram_file_unique_id,
                    file_name=attachment.file_name,
                    mime_type=attachment.mime_type,
                    file_size=attachment.file_size,
                    source_chat_id=attachment.source_chat_id,
                    source_message_id=attachment.source_message_id,
                    duration_seconds=attachment.duration_seconds,
                    width=attachment.width,
                    height=attachment.height,
                )
            )
            session.add(submission)
            await ProgressionService.record_submission(
                session,
                enrollment_id=row.enrollment_id,
                lesson_id=row.lesson_id,
            )
            self._clear_waiting_state(row)

            return self._receipt(row, attempt_number)

    async def cancel(self, telegram_user_id: int) -> bool:
        async with session_scope(self._session_factory) as session:
            bot_state = await session.scalar(
                select(StudentBotState)
                .join(Student, Student.id == StudentBotState.student_id)
                .where(
                    Student.telegram_user_id == telegram_user_id,
                    StudentBotState.state == ConversationState.AWAITING_HOMEWORK,
                )
            )
            if bot_state is None:
                return False

            bot_state.state = ConversationState.IDLE
            bot_state.assignment_id = None
            return True

    @staticmethod
    async def _get_waiting_context(
        session: AsyncSession,
        telegram_user_id: int,
    ) -> Any:
        row = (
            await session.execute(
                select(
                    StudentBotState,
                    Enrollment.id.label("enrollment_id"),
                    Lesson.id.label("lesson_id"),
                    Lesson.position,
                    Lesson.title,
                    Assignment.id.label("assignment_id"),
                    Assignment.submission_kind,
                )
                .join(Student, Student.id == StudentBotState.student_id)
                .join(Assignment, Assignment.id == StudentBotState.assignment_id)
                .join(Lesson, Lesson.id == Assignment.lesson_id)
                .join(Course, Course.id == Lesson.course_id)
                .join(Cohort, Cohort.course_id == Course.id)
                .join(
                    Enrollment,
                    (Enrollment.cohort_id == Cohort.id) & (Enrollment.student_id == Student.id),
                )
                .where(
                    Student.telegram_user_id == telegram_user_id,
                    StudentBotState.state == ConversationState.AWAITING_HOMEWORK,
                    Enrollment.status == EnrollmentStatus.ACTIVE,
                )
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise NotAwaitingSubmissionError
        return row

    @staticmethod
    async def _next_attempt_number(session: AsyncSession, row: Any) -> int:
        previous_attempt = await session.scalar(
            select(func.max(Submission.attempt_number)).where(
                Submission.enrollment_id == row.enrollment_id,
                Submission.assignment_id == row.assignment_id,
            )
        )
        return (previous_attempt or 0) + 1

    @staticmethod
    def _clear_waiting_state(row: Any) -> None:
        row.StudentBotState.state = ConversationState.IDLE
        row.StudentBotState.assignment_id = None

    @staticmethod
    def _receipt(row: Any, attempt_number: int) -> SubmissionReceipt:
        return SubmissionReceipt(
            lesson_position=row.position,
            lesson_title=row.title,
            attempt_number=attempt_number,
        )
