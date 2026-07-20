"""Curator-facing view over Telegram student questions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    TelegramQuestionAttachment,
)
from course_platform.models.enums import AttachmentKind, StaffRole
from course_platform.services.access_scope import StaffScope
from course_platform.services.submissions import HomeworkAttachment


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
class QuestionAnswerAttachmentInput:
    kind: AttachmentKind
    local_path: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


@dataclass(frozen=True, slots=True)
class TelegramQuestionAttachmentOverview:
    id: UUID
    source: str
    kind: AttachmentKind
    file_name: str | None
    mime_type: str | None
    file_size: int | None


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
    status: str
    answer_text: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    attachments: tuple[TelegramQuestionAttachmentOverview, ...] = ()


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
class RecentAnsweredQuestionTarget:
    question_id: UUID
    student_telegram_user_id: int | None


@dataclass(frozen=True, slots=True)
class RecentQuestionAttachmentTarget:
    question_id: UUID
    curator_telegram_user_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TelegramQuestionAttachmentSource:
    kind: AttachmentKind
    telegram_file_id: str | None
    local_path: str | None
    file_name: str | None
    mime_type: str | None
    file_size: int | None


def _attachment_overview(
    attachment: TelegramQuestionAttachment,
) -> TelegramQuestionAttachmentOverview:
    return TelegramQuestionAttachmentOverview(
        id=attachment.id,
        source=attachment.source,
        kind=attachment.kind,
        file_name=attachment.file_name,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
    )


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
            rows = (await session.execute(query)).all()

            question_ids = [row[0].id for row in rows]
            attachments_by_question: dict[UUID, list[TelegramQuestionAttachmentOverview]] = {
                question_id: [] for question_id in question_ids
            }
            if question_ids:
                attachment_rows = await session.scalars(
                    select(TelegramQuestionAttachment)
                    .where(TelegramQuestionAttachment.question_id.in_(question_ids))
                    .order_by(TelegramQuestionAttachment.created_at.asc())
                )
                for attachment in attachment_rows:
                    attachments_by_question[attachment.question_id].append(
                        _attachment_overview(attachment)
                    )

            return [
                self._overview(*row, attachments=attachments_by_question[row[0].id])
                for row in rows
            ]

    async def find_recent_open_question(
        self,
        telegram_user_id: int,
        *,
        within_seconds: int = 120,
    ) -> RecentQuestionAttachmentTarget | None:
        """Find a just-asked open question to attach a late album photo to.

        Telegram delivers an album as separate messages. By the time the
        second photo arrives, the question has already been created and the
        student's conversation state cleared, so this catches that stray
        photo instead of letting it fall through into a homework submission.
        """
        async with self._session_factory() as session:
            cutoff = datetime.now(UTC) - timedelta(seconds=within_seconds)
            row = (
                await session.execute(
                    select(TelegramQuestion, Student.assigned_curator_id)
                    .join(Student, Student.id == TelegramQuestion.student_id)
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        TelegramQuestion.status == "open",
                        TelegramQuestion.created_at >= cutoff,
                    )
                    .order_by(TelegramQuestion.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            question, assigned_curator_id = row

            curator_telegram_user_ids: tuple[int, ...] = ()
            if assigned_curator_id is not None:
                curator_telegram_user_ids = tuple(
                    await session.scalars(
                        select(StaffUser.telegram_user_id).where(
                            StaffUser.id == assigned_curator_id,
                            StaffUser.is_active.is_(True),
                            StaffUser.telegram_user_id.is_not(None),
                        )
                    )
                )
            if not curator_telegram_user_ids:
                curator_telegram_user_ids = tuple(
                    await session.scalars(
                        select(StaffUser.telegram_user_id).where(
                            StaffUser.is_active.is_(True),
                            StaffUser.telegram_user_id.is_not(None),
                        )
                    )
                )
            return RecentQuestionAttachmentTarget(
                question_id=question.id,
                curator_telegram_user_ids=curator_telegram_user_ids,
            )

    async def find_recently_answered_question(
        self,
        reviewer_telegram_user_id: int,
        *,
        within_seconds: int = 120,
    ) -> RecentAnsweredQuestionTarget | None:
        """Find a question this curator just answered, to forward a late album photo.

        Mirrors find_recent_open_question but on the curator side: the first
        photo of an album completes the reply and clears the pending-reply
        state, so the rest need somewhere to land instead of "Не понял
        сообщение".
        """
        async with self._session_factory() as session:
            cutoff = datetime.now(UTC) - timedelta(seconds=within_seconds)
            row = (
                await session.execute(
                    select(TelegramQuestion, Student.telegram_user_id)
                    .join(StaffUser, StaffUser.id == TelegramQuestion.resolved_by_staff_id)
                    .join(Student, Student.id == TelegramQuestion.student_id)
                    .where(
                        StaffUser.telegram_user_id == reviewer_telegram_user_id,
                        TelegramQuestion.status == "resolved",
                        TelegramQuestion.resolved_at >= cutoff,
                    )
                    .order_by(TelegramQuestion.resolved_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            question, student_telegram_user_id = row
            return RecentAnsweredQuestionTarget(
                question_id=question.id,
                student_telegram_user_id=student_telegram_user_id,
            )

    async def add_attachment(
        self,
        *,
        question_id: UUID,
        source: str,
        kind: AttachmentKind,
        telegram_file_id: str | None = None,
        telegram_file_unique_id: str | None = None,
        local_path: str | None = None,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
    ) -> None:
        """Record a late-arriving attachment (album tail) against a question."""
        async with session_scope(self._session_factory) as session:
            session.add(
                TelegramQuestionAttachment(
                    question_id=question_id,
                    source=source,
                    kind=kind,
                    telegram_file_id=telegram_file_id,
                    telegram_file_unique_id=telegram_file_unique_id,
                    local_path=local_path,
                    source_chat_id=source_chat_id,
                    source_message_id=source_message_id,
                    file_name=file_name,
                    mime_type=mime_type,
                    file_size=file_size,
                )
            )

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
        attachments: tuple[QuestionAnswerAttachmentInput, ...] = (),
        viewer: StaffScope | None = None,
    ) -> QuestionPanelAnswer:
        normalized = message.strip()
        if not normalized and not attachments:
            raise EmptyQuestionAnswerError
        if not normalized:
            normalized = "См. вложение куратора."

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
            for attachment in attachments:
                session.add(
                    TelegramQuestionAttachment(
                        question_id=question.id,
                        source="curator",
                        kind=attachment.kind,
                        local_path=attachment.local_path,
                        file_name=attachment.file_name,
                        mime_type=attachment.mime_type,
                        file_size=attachment.file_size,
                    )
                )
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
        attachment_id: UUID,
    ) -> TelegramQuestionAttachmentSource:
        async with self._session_factory() as session:
            attachment = await session.scalar(
                select(TelegramQuestionAttachment).where(
                    TelegramQuestionAttachment.id == attachment_id,
                    TelegramQuestionAttachment.question_id == question_id,
                )
            )
            if attachment is None:
                raise TelegramQuestionAttachmentNotFoundError
            return TelegramQuestionAttachmentSource(
                kind=attachment.kind,
                telegram_file_id=attachment.telegram_file_id,
                local_path=attachment.local_path,
                file_name=attachment.file_name,
                mime_type=attachment.mime_type,
                file_size=attachment.file_size,
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
        attachment: HomeworkAttachment | None = None,
    ) -> QuestionReplyCompletion:
        pending = await self.get_pending_reply(reviewer_telegram_user_id)
        if pending is None:
            raise NoPendingQuestionReplyError

        normalized = message.strip()
        if not normalized and attachment is None:
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
            if attachment is not None:
                session.add(
                    TelegramQuestionAttachment(
                        question_id=question.id,
                        source="curator",
                        kind=attachment.kind,
                        telegram_file_id=attachment.telegram_file_id,
                        telegram_file_unique_id=attachment.telegram_file_unique_id,
                        source_chat_id=attachment.source_chat_id,
                        source_message_id=attachment.source_message_id,
                        file_name=attachment.file_name,
                        mime_type=attachment.mime_type,
                        file_size=attachment.file_size,
                    )
                )
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
        attachment_rows = await session.scalars(
            select(TelegramQuestionAttachment)
            .where(TelegramQuestionAttachment.question_id == question_id)
            .order_by(TelegramQuestionAttachment.created_at.asc())
        )
        attachments = [_attachment_overview(attachment) for attachment in attachment_rows]
        return self._overview(*row, attachments=attachments)

    @staticmethod
    def _overview(
        question: TelegramQuestion,
        student: Student,
        lesson: Lesson | None,
        course: Course | None,
        staff: StaffUser | None,
        *,
        attachments: list[TelegramQuestionAttachmentOverview] | None = None,
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
            status=question.status,
            answer_text=question.answer_text,
            created_at=question.created_at,
            resolved_at=question.resolved_at,
            resolved_by=staff.display_name if staff else None,
            attachments=tuple(attachments or ()),
        )
