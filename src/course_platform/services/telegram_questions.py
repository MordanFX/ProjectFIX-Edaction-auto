"""Curator-facing view over Telegram student questions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Course,
    Lesson,
    StaffBotState,
    StaffUser,
    Student,
    TelegramQuestion,
)
from course_platform.models.enums import AttachmentKind, StaffRole
from course_platform.services.access_scope import StaffScope


class TelegramQuestionNotFoundError(RuntimeError):
    pass


class TelegramQuestionAttachmentNotFoundError(RuntimeError):
    pass


class TelegramQuestionAlreadyResolvedError(RuntimeError):
    pass


class UnauthorizedQuestionReviewerError(RuntimeError):
    pass


class NoPendingQuestionReplyError(RuntimeError):
    pass


class EmptyQuestionReplyError(RuntimeError):
    pass


class EmptyQuestionAnswerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramQuestionOverview:
    question_id: UUID
    student_id: UUID
    student_name: str
    student_username: str | None
    lesson_position: int | None
    lesson_title: str | None
    course_title: str | None
    text_body: str | None
    has_attachment: bool
    attachment_kind: AttachmentKind | None
    status: str
    answer_text: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None


@dataclass(frozen=True, slots=True)
class QuestionReplyPrompt:
    question_id: UUID
    student_name: str
    lesson_position: int | None
    lesson_title: str | None
    question_text: str | None


@dataclass(frozen=True, slots=True)
class PendingQuestionReply:
    question_id: UUID
    reviewer_id: UUID


@dataclass(frozen=True, slots=True)
class QuestionReplyCompletion:
    question_id: UUID
    student_telegram_user_id: int | None
    student_name: str
    lesson_position: int | None
    lesson_title: str | None
    message: str


@dataclass(frozen=True, slots=True)
class QuestionPanelAnswer:
    overview: TelegramQuestionOverview
    student_telegram_user_id: int | None


@dataclass(frozen=True, slots=True)
class TelegramQuestionAttachmentSource:
    kind: AttachmentKind
    telegram_file_id: str | None
    file_name: str | None
    mime_type: str | None
    file_size: int | None


class TelegramQuestionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_questions(
        self,
        *,
        include_resolved: bool = True,
        viewer: StaffScope | None = None,
    ) -> list[TelegramQuestionOverview]:
        async with self._session_factory() as session:
            query = (
                select(TelegramQuestion, Student, Lesson, Course, StaffUser)
                .join(Student, Student.id == TelegramQuestion.student_id)
                .outerjoin(Assignment, Assignment.id == TelegramQuestion.assignment_id)
                .outerjoin(Lesson, Lesson.id == Assignment.lesson_id)
                .outerjoin(Course, Course.id == Lesson.course_id)
                .outerjoin(StaffUser, StaffUser.id == TelegramQuestion.resolved_by_staff_id)
                .order_by(TelegramQuestion.created_at.desc())
            )
            if not include_resolved:
                query = query.where(TelegramQuestion.status == "open")
            if viewer is not None and not viewer.is_admin:
                query = query.where(
                    or_(
                        Student.assigned_curator_id.is_(None),
                        Student.assigned_curator_id == viewer.staff_id,
                    )
                )
            return [self._overview(*row) for row in (await session.execute(query)).all()]

    async def resolve_question(
        self,
        *,
        question_id: UUID,
        staff_id: UUID,
        viewer: StaffScope | None = None,
    ) -> TelegramQuestionOverview:
        async with session_scope(self._session_factory) as session:
            question = await session.get(TelegramQuestion, question_id)
            if question is None:
                raise TelegramQuestionNotFoundError
            if viewer is not None and not viewer.is_admin:
                student = await session.get(Student, question.student_id)
                if student is not None and student.assigned_curator_id not in (
                    None,
                    viewer.staff_id,
                ):
                    raise TelegramQuestionNotFoundError
            question.status = "resolved"
            question.resolved_at = datetime.now(UTC)
            question.resolved_by_staff_id = staff_id
            await session.flush()
            return await self._question_by_id(session, question.id)

    async def answer_question(
        self,
        *,
        question_id: UUID,
        staff_id: UUID,
        message: str,
        viewer: StaffScope | None = None,
    ) -> QuestionPanelAnswer:
        normalized = message.strip()
        if not normalized:
            raise EmptyQuestionAnswerError

        async with session_scope(self._session_factory) as session:
            row = (
                await session.execute(
                    select(TelegramQuestion, Student)
                    .join(Student, Student.id == TelegramQuestion.student_id)
                    .where(TelegramQuestion.id == question_id)
                )
            ).one_or_none()
            if row is None:
                raise TelegramQuestionNotFoundError
            question, student = row
            if viewer is not None and not viewer.is_admin and student.assigned_curator_id not in (
                None,
                viewer.staff_id,
            ):
                raise TelegramQuestionNotFoundError
            if question.status != "open":
                raise TelegramQuestionAlreadyResolvedError

            question.status = "resolved"
            question.answer_text = normalized
            question.resolved_at = datetime.now(UTC)
            question.resolved_by_staff_id = staff_id
            student_telegram_user_id = student.telegram_user_id
            await session.flush()
            overview = await self._question_by_id(session, question.id)
            return QuestionPanelAnswer(
                overview=overview,
                student_telegram_user_id=student_telegram_user_id,
            )

    async def get_attachment_media_source(
        self,
        *,
        question_id: UUID,
    ) -> TelegramQuestionAttachmentSource:
        async with self._session_factory() as session:
            question = await session.get(TelegramQuestion, question_id)
            if question is None or question.attachment_kind is None:
                raise TelegramQuestionAttachmentNotFoundError
            return TelegramQuestionAttachmentSource(
                kind=question.attachment_kind,
                telegram_file_id=question.attachment_telegram_file_id,
                file_name=question.attachment_file_name,
                mime_type=question.attachment_mime_type,
                file_size=question.attachment_file_size,
            )

    async def begin_reply(
        self,
        *,
        question_id: UUID,
        reviewer_telegram_user_id: int,
    ) -> QuestionReplyPrompt:
        async with session_scope(self._session_factory) as session:
            reviewer = await session.scalar(
                select(StaffUser).where(
                    StaffUser.telegram_user_id == reviewer_telegram_user_id,
                    StaffUser.is_active.is_(True),
                )
            )
            if reviewer is None:
                raise UnauthorizedQuestionReviewerError

            row = (
                await session.execute(
                    select(TelegramQuestion, Student, Lesson)
                    .join(Student, Student.id == TelegramQuestion.student_id)
                    .outerjoin(Assignment, Assignment.id == TelegramQuestion.assignment_id)
                    .outerjoin(Lesson, Lesson.id == Assignment.lesson_id)
                    .where(TelegramQuestion.id == question_id)
                )
            ).one_or_none()
            if row is None:
                raise TelegramQuestionNotFoundError
            question, student, lesson = row
            if question.status != "open":
                raise TelegramQuestionAlreadyResolvedError
            if reviewer.role is not StaffRole.ADMIN and student.assigned_curator_id not in (
                None,
                reviewer.id,
            ):
                raise TelegramQuestionNotFoundError

            state = await session.get(StaffBotState, reviewer.id)
            if state is None:
                state = StaffBotState(staff_id=reviewer.id)
                session.add(state)
            state.question_id = question.id
            state.submission_id = None
            state.verdict = None
            state.source_chat_id = None
            state.source_message_id = None

            student_name = " ".join(
                part for part in (student.first_name, student.last_name) if part
            )
            return QuestionReplyPrompt(
                question_id=question.id,
                student_name=student_name,
                lesson_position=lesson.position if lesson else None,
                lesson_title=lesson.title if lesson else None,
                question_text=question.text_body,
            )

    async def get_pending_reply(
        self,
        reviewer_telegram_user_id: int,
    ) -> PendingQuestionReply | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(StaffBotState, StaffUser)
                    .join(StaffUser, StaffUser.id == StaffBotState.staff_id)
                    .where(
                        StaffUser.telegram_user_id == reviewer_telegram_user_id,
                        StaffUser.is_active.is_(True),
                        StaffBotState.question_id.is_not(None),
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            state, reviewer = row
            return PendingQuestionReply(question_id=state.question_id, reviewer_id=reviewer.id)

    async def complete_reply(
        self,
        *,
        reviewer_telegram_user_id: int,
        message: str,
        has_attachment: bool = False,
    ) -> QuestionReplyCompletion:
        pending = await self.get_pending_reply(reviewer_telegram_user_id)
        if pending is None:
            raise NoPendingQuestionReplyError

        normalized = message.strip()
        if not normalized and not has_attachment:
            raise EmptyQuestionReplyError
        if not normalized:
            normalized = "См. вложение куратора."

        async with session_scope(self._session_factory) as session:
            row = (
                await session.execute(
                    select(TelegramQuestion, Student, Lesson)
                    .join(Student, Student.id == TelegramQuestion.student_id)
                    .outerjoin(Assignment, Assignment.id == TelegramQuestion.assignment_id)
                    .outerjoin(Lesson, Lesson.id == Assignment.lesson_id)
                    .where(TelegramQuestion.id == pending.question_id)
                )
            ).one_or_none()
            state = await session.get(StaffBotState, pending.reviewer_id)
            if row is None:
                if state is not None:
                    await session.delete(state)
                raise TelegramQuestionNotFoundError
            question, student, lesson = row

            question.status = "resolved"
            question.answer_text = normalized
            question.resolved_at = datetime.now(UTC)
            question.resolved_by_staff_id = pending.reviewer_id
            if state is not None:
                await session.delete(state)

            student_name = " ".join(
                part for part in (student.first_name, student.last_name) if part
            )
            return QuestionReplyCompletion(
                question_id=question.id,
                student_telegram_user_id=student.telegram_user_id,
                student_name=student_name,
                lesson_position=lesson.position if lesson else None,
                lesson_title=lesson.title if lesson else None,
                message=normalized,
            )

    async def _question_by_id(
        self,
        session: AsyncSession,
        question_id: UUID,
    ) -> TelegramQuestionOverview:
        row = (
            await session.execute(
                select(TelegramQuestion, Student, Lesson, Course, StaffUser)
                .join(Student, Student.id == TelegramQuestion.student_id)
                .outerjoin(Assignment, Assignment.id == TelegramQuestion.assignment_id)
                .outerjoin(Lesson, Lesson.id == Assignment.lesson_id)
                .outerjoin(Course, Course.id == Lesson.course_id)
                .outerjoin(StaffUser, StaffUser.id == TelegramQuestion.resolved_by_staff_id)
                .where(TelegramQuestion.id == question_id)
            )
        ).one()
        return self._overview(*row)

    @staticmethod
    def _overview(
        question: TelegramQuestion,
        student: Student,
        lesson: Lesson | None,
        course: Course | None,
        staff: StaffUser | None,
    ) -> TelegramQuestionOverview:
        student_name = " ".join(
            part for part in (student.first_name, student.last_name) if part
        )
        return TelegramQuestionOverview(
            question_id=question.id,
            student_id=question.student_id,
            student_name=student_name,
            student_username=student.username,
            lesson_position=lesson.position if lesson else None,
            lesson_title=lesson.title if lesson else None,
            course_title=course.title if course else None,
            text_body=question.text_body,
            has_attachment=question.attachment_kind is not None,
            attachment_kind=question.attachment_kind,
            status=question.status,
            answer_text=question.answer_text,
            created_at=question.created_at,
            resolved_at=question.resolved_at,
            resolved_by=staff.display_name if staff else None,
        )
