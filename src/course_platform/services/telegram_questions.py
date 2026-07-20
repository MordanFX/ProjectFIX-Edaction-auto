"""Curator-facing view over Telegram student questions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Course,
    Lesson,
    StaffUser,
    Student,
    TelegramQuestion,
)
from course_platform.models.enums import AttachmentKind


class TelegramQuestionNotFoundError(RuntimeError):
    pass


class TelegramQuestionAttachmentNotFoundError(RuntimeError):
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
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None


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
            return [self._overview(*row) for row in (await session.execute(query)).all()]

    async def resolve_question(
        self,
        *,
        question_id: UUID,
        staff_id: UUID,
    ) -> TelegramQuestionOverview:
        async with session_scope(self._session_factory) as session:
            question = await session.get(TelegramQuestion, question_id)
            if question is None:
                raise TelegramQuestionNotFoundError
            question.status = "resolved"
            question.resolved_at = datetime.now(UTC)
            question.resolved_by_staff_id = staff_id
            await session.flush()
            return await self._question_by_id(session, question.id)

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
            created_at=question.created_at,
            resolved_at=question.resolved_at,
            resolved_by=staff.display_name if staff else None,
        )
