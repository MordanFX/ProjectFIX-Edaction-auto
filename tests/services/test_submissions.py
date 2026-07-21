"""Persistent text homework workflow tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import (
    Assignment,
    Lesson,
    StaffBotState,
    StaffUser,
    Student,
    StudentBotState,
    Submission,
    SubmissionAttachment,
    TelegramQuestion,
    TelegramQuestionAttachment,
)
from course_platform.models.enums import (
    AttachmentKind,
    ConversationState,
    SubmissionKind,
    SubmissionStatus,
)
from course_platform.services.progression import ProgressionService
from course_platform.services.students import StudentRegistration, StudentService
from course_platform.services.submissions import (
    HomeworkAttachment,
    LessonNotViewedError,
    NotAwaitingQuestionError,
    NotAwaitingSubmissionError,
    SubmissionPendingError,
    SubmissionService,
    UnsupportedSubmissionKindError,
)
from course_platform.services.telegram_questions import (
    EmptyQuestionAnswerError,
    EmptyQuestionReplyError,
    NoPendingQuestionReplyError,
    QuestionAnswerAttachmentInput,
    TelegramQuestionAlreadyResolvedError,
    TelegramQuestionService,
    UnauthorizedQuestionReviewerError,
)


async def test_homework_is_locked_until_lesson_view_is_confirmed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=124, first_name="Viewer")
    )
    await seed_demo_data(session_factory)
    service = SubmissionService(session_factory)

    with pytest.raises(LessonNotViewedError):
        await service.begin(124)

    await ProgressionService(session_factory).mark_current_viewed(124)
    prompt = await service.begin(124)

    assert prompt.lesson_position == 1


async def prepare_student(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    telegram_user_id: int = 123,
) -> SubmissionService:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=telegram_user_id, first_name="Student")
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(telegram_user_id)
    return SubmissionService(session_factory)


async def test_text_submission_requires_explicit_begin_and_clears_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)

    with pytest.raises(NotAwaitingSubmissionError):
        await service.submit_text(123, "Answer before begin")

    prompt = await service.begin(123)
    receipt = await service.submit_text(123, "  My homework answer  ")
    journal = await service.journal(123)

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        bot_state = await session.scalar(select(StudentBotState))

    assert prompt.lesson_position == 1
    assert receipt.attempt_number == 1
    assert len(journal) == 1
    assert journal[0].lesson_position == 1
    assert journal[0].status is SubmissionStatus.SUBMITTED
    assert submission is not None
    assert submission.text_body == "My homework answer"
    assert submission.status is SubmissionStatus.SUBMITTED
    assert bot_state is not None
    assert bot_state.state is ConversationState.IDLE
    assert bot_state.assignment_id is None


async def test_pending_submission_cannot_be_sent_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    await service.begin(123)
    await service.submit_text(123, "First attempt")

    with pytest.raises(SubmissionPendingError):
        await service.begin(123)


async def test_revision_request_creates_next_attempt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    await service.begin(123)
    await service.submit_text(123, "First attempt")

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        assert submission is not None
        submission.status = SubmissionStatus.REVISION_REQUESTED
        await session.commit()

    await service.begin(123)
    receipt = await service.submit_text(123, "Second attempt")

    async with session_factory() as session:
        submissions = list(
            await session.scalars(select(Submission).order_by(Submission.attempt_number))
        )

    assert receipt.attempt_number == 2
    assert [submission.text_body for submission in submissions] == [
        "First attempt",
        "Second attempt",
    ]


async def test_cancel_clears_waiting_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    await service.begin(123)

    assert await service.cancel(123) is True
    assert await service.cancel(123) is False
    with pytest.raises(NotAwaitingSubmissionError):
        await service.submit_text(123, "Cancelled answer")


async def test_document_submission_persists_attachment_and_caption(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    await service.begin(123)

    receipt = await service.submit_attachment(
        123,
        HomeworkAttachment(
            kind=AttachmentKind.DOCUMENT,
            telegram_file_id="bot-file-id",
            telegram_file_unique_id="stable-file-id",
            file_name="homework.pdf",
            mime_type="application/pdf",
            file_size=1024,
        ),
        caption="  Result description  ",
    )

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        attachment = await session.scalar(select(SubmissionAttachment))

    assert receipt.attempt_number == 1
    assert submission is not None
    assert submission.text_body == "Result description"
    assert attachment is not None
    assert attachment.kind is AttachmentKind.DOCUMENT
    assert attachment.file_name == "homework.pdf"
    assert attachment.telegram_file_id == "bot-file-id"


async def test_wrong_attachment_kind_keeps_submission_open(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    async with session_factory() as session:
        assignment = await session.scalar(select(Assignment))
        assert assignment is not None
        assignment.submission_kind = SubmissionKind.TEXT
        await session.commit()

    await service.begin(123)
    with pytest.raises(UnsupportedSubmissionKindError):
        await service.submit_attachment(
            123,
            HomeworkAttachment(
                kind=AttachmentKind.PHOTO,
                telegram_file_id="photo-id",
                telegram_file_unique_id="photo-unique-id",
            ),
        )

    receipt = await service.submit_text(123, "Correct text response")
    assert receipt.attempt_number == 1


async def test_question_text_persists_and_is_awaiting_flips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
    assert lesson is not None

    assert await service.is_awaiting_question(123) is False
    with pytest.raises(NotAwaitingQuestionError):
        await service.submit_question_text(123, "Too early")

    await service.begin_question(123, expected_lesson_id=lesson.id)
    assert await service.is_awaiting_question(123) is True

    receipt = await service.submit_question_text(123, "  How do I submit?  ")
    assert receipt.question_text == "How do I submit?"
    assert receipt.attachment_kind is None
    assert await service.is_awaiting_question(123) is False

    async with session_factory() as session:
        question = await session.scalar(select(TelegramQuestion))
    assert question is not None
    assert question.text_body == "How do I submit?"
    assert question.status == "open"


async def test_question_attachment_is_saved_instead_of_homework(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
    assert lesson is not None
    await service.begin_question(123, expected_lesson_id=lesson.id)

    receipt = await service.submit_question_attachment(
        123,
        HomeworkAttachment(
            kind=AttachmentKind.PHOTO,
            telegram_file_id="question-photo",
            telegram_file_unique_id="question-photo-unique",
            source_chat_id=123,
            source_message_id=9,
        ),
        caption="Look at this screenshot",
    )
    assert receipt.attachment_kind is AttachmentKind.PHOTO
    assert receipt.question_text == "Look at this screenshot"

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        question = await session.scalar(select(TelegramQuestion))
        attachment = await session.scalar(select(TelegramQuestionAttachment))
    assert submission is None
    assert question is not None
    assert question.text_body == "Look at this screenshot"
    assert attachment is not None
    assert attachment.source == "student"
    assert attachment.kind is AttachmentKind.PHOTO
    assert attachment.telegram_file_id == "question-photo"


async def test_telegram_question_is_listed_and_resolved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
    assert lesson is not None
    await service.begin_question(123, expected_lesson_id=lesson.id)
    receipt = await service.submit_question_text(123, "Need help")

    async with session_factory() as session:
        staff = StaffUser(login="curator", display_name="Curator")
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    questions_service = TelegramQuestionService(session_factory)
    open_questions = await questions_service.list_questions(include_resolved=False)
    assert [item.question_id for item in open_questions] == [receipt.question_id]
    assert open_questions[0].text_body == "Need help"
    assert open_questions[0].status == "open"

    resolved = await questions_service.resolve_question(
        question_id=receipt.question_id,
        staff_id=staff_id,
    )
    assert resolved.status == "resolved"
    assert resolved.resolved_by == "Curator"

    still_open = await questions_service.list_questions(include_resolved=False)
    assert still_open == []


async def ask_question(
    session_factory: async_sessionmaker[AsyncSession],
    submission_service: SubmissionService,
    *,
    telegram_user_id: int = 123,
    text: str = "Need help",
):
    async with session_factory() as session:
        lesson = await session.scalar(select(Lesson).order_by(Lesson.position))
    assert lesson is not None
    await submission_service.begin_question(telegram_user_id, expected_lesson_id=lesson.id)
    return await submission_service.submit_question_text(telegram_user_id, text)


async def test_curator_can_reply_to_telegram_question(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_service = await prepare_student(session_factory)
    receipt = await ask_question(session_factory, submission_service)

    async with session_factory() as session:
        staff = StaffUser(login="curator", display_name="Curator", telegram_user_id=999)
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    questions_service = TelegramQuestionService(session_factory)

    with pytest.raises(UnauthorizedQuestionReviewerError):
        await questions_service.begin_reply(
            question_id=receipt.question_id,
            reviewer_telegram_user_id=555555,
        )

    assert await questions_service.get_pending_reply(999) is None

    prompt = await questions_service.begin_reply(
        question_id=receipt.question_id,
        reviewer_telegram_user_id=999,
    )
    assert prompt.question_id == receipt.question_id
    assert prompt.lesson_position == 1

    pending = await questions_service.get_pending_reply(999)
    assert pending is not None
    assert pending.question_id == receipt.question_id

    with pytest.raises(EmptyQuestionReplyError):
        await questions_service.complete_reply(reviewer_telegram_user_id=999, message="   ")

    completion = await questions_service.complete_reply(
        reviewer_telegram_user_id=999,
        message="  Here is the answer  ",
    )
    assert completion.question_id == receipt.question_id
    assert completion.student_telegram_user_id == 123
    assert completion.message == "Here is the answer"

    assert await questions_service.get_pending_reply(999) is None
    async with session_factory() as session:
        state = await session.get(StaffBotState, staff_id)
        question = await session.get(TelegramQuestion, receipt.question_id)
    assert state is None
    assert question is not None
    assert question.status == "resolved"
    assert question.answer_text == "Here is the answer"
    assert question.resolved_by_staff_id == staff_id

    with pytest.raises(NoPendingQuestionReplyError):
        await questions_service.complete_reply(reviewer_telegram_user_id=999, message="Late reply")


async def test_curator_reply_attachment_is_saved_for_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_service = await prepare_student(session_factory)
    receipt = await ask_question(session_factory, submission_service)

    async with session_factory() as session:
        staff = StaffUser(login="curator-photo", display_name="Curator", telegram_user_id=998)
        session.add(staff)
        await session.commit()

    questions_service = TelegramQuestionService(session_factory)
    await questions_service.begin_reply(
        question_id=receipt.question_id,
        reviewer_telegram_user_id=998,
    )
    await questions_service.complete_reply(
        reviewer_telegram_user_id=998,
        message="See the attached screenshot",
        attachment=HomeworkAttachment(
            kind=AttachmentKind.PHOTO,
            telegram_file_id="answer-photo",
            telegram_file_unique_id="answer-photo-unique",
            source_chat_id=998,
            source_message_id=42,
        ),
    )

    async with session_factory() as session:
        attachment = await session.scalar(
            select(TelegramQuestionAttachment).where(
                TelegramQuestionAttachment.question_id == receipt.question_id
            )
        )
    assert attachment is not None
    assert attachment.source == "curator"
    assert attachment.telegram_file_id == "answer-photo"


async def test_panel_answer_attachment_is_saved_for_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_service = await prepare_student(session_factory)
    receipt = await ask_question(session_factory, submission_service)

    async with session_factory() as session:
        staff = StaffUser(login="panel-curator-2", display_name="Panel Curator")
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    questions_service = TelegramQuestionService(session_factory)
    result = await questions_service.answer_question(
        question_id=receipt.question_id,
        staff_id=staff_id,
        message="See the attached file",
        attachments=(
            QuestionAnswerAttachmentInput(
                kind=AttachmentKind.DOCUMENT,
                local_path="data/feedback_uploads/answer-file.pdf",
                file_name="answer-file.pdf",
                mime_type="application/pdf",
                file_size=2048,
            ),
        ),
    )
    assert result.overview.answer_text == "See the attached file"

    async with session_factory() as session:
        attachment = await session.scalar(
            select(TelegramQuestionAttachment).where(
                TelegramQuestionAttachment.question_id == receipt.question_id
            )
        )
    assert attachment is not None
    assert attachment.source == "curator"
    assert attachment.local_path == "data/feedback_uploads/answer-file.pdf"


async def test_cannot_reply_to_already_resolved_question(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_service = await prepare_student(session_factory)
    receipt = await ask_question(session_factory, submission_service)

    async with session_factory() as session:
        staff = StaffUser(login="curator2", display_name="Curator Two", telegram_user_id=888)
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    questions_service = TelegramQuestionService(session_factory)
    await questions_service.resolve_question(question_id=receipt.question_id, staff_id=staff_id)

    with pytest.raises(TelegramQuestionAlreadyResolvedError):
        await questions_service.begin_reply(
            question_id=receipt.question_id,
            reviewer_telegram_user_id=888,
        )


async def test_stale_pending_reply_expires_instead_of_silently_resolving(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A curator who pressed "Ответить" long ago and forgot must not have a
    much later, unrelated message silently resolve that stale question."""
    submission_service = await prepare_student(session_factory)
    receipt = await ask_question(session_factory, submission_service)

    async with session_factory() as session:
        staff = StaffUser(login="curator-stale", display_name="Stale Curator", telegram_user_id=997)
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    questions_service = TelegramQuestionService(session_factory)
    await questions_service.begin_reply(
        question_id=receipt.question_id,
        reviewer_telegram_user_id=997,
    )
    assert await questions_service.has_pending_reply(997) is True

    async with session_factory() as session:
        state = await session.get(StaffBotState, staff_id)
        assert state is not None
        state.updated_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    assert await questions_service.get_pending_reply(997) is None
    assert await questions_service.has_pending_reply(997) is False

    with pytest.raises(NoPendingQuestionReplyError):
        await questions_service.complete_reply(
            reviewer_telegram_user_id=997, message="Too late now"
        )

    async with session_factory() as session:
        question = await session.get(TelegramQuestion, receipt.question_id)
    assert question is not None
    assert question.status == "open"


async def test_question_notifies_only_the_assigned_curator(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    async with session_factory() as session:
        other_curator = StaffUser(
            login="other-curator", display_name="Other", telegram_user_id=444
        )
        pinned_curator = StaffUser(
            login="pinned-curator", display_name="Pinned", telegram_user_id=555
        )
        session.add_all([other_curator, pinned_curator])
        await session.flush()
        student = await session.scalar(select(Student).where(Student.telegram_user_id == 123))
        assert student is not None
        student.assigned_curator_id = pinned_curator.id
        await session.commit()

    receipt = await ask_question(session_factory, service, text="Only for my curator")
    assert receipt.curator_telegram_user_ids == (555,)


async def test_unassigned_student_question_notifies_all_active_curators(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = await prepare_student(session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                StaffUser(login="curator-x", display_name="X", telegram_user_id=666),
                StaffUser(login="curator-y", display_name="Y", telegram_user_id=777),
            ]
        )
        await session.commit()

    receipt = await ask_question(session_factory, service, text="For anyone")
    assert {666, 777}.issubset(receipt.curator_telegram_user_ids)


async def test_curator_can_answer_question_from_panel(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_service = await prepare_student(session_factory)
    receipt = await ask_question(session_factory, submission_service, text="Panel question")

    async with session_factory() as session:
        staff = StaffUser(login="panel-curator", display_name="Panel Curator")
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    questions_service = TelegramQuestionService(session_factory)

    with pytest.raises(EmptyQuestionAnswerError):
        await questions_service.answer_question(
            question_id=receipt.question_id, staff_id=staff_id, message="   "
        )

    result = await questions_service.answer_question(
        question_id=receipt.question_id,
        staff_id=staff_id,
        message="  Here is the panel answer  ",
    )
    assert result.student_telegram_user_id == 123
    assert result.overview.status == "resolved"
    assert result.overview.answer_text == "Here is the panel answer"
    assert result.overview.resolved_by == "Panel Curator"

    with pytest.raises(TelegramQuestionAlreadyResolvedError):
        await questions_service.answer_question(
            question_id=receipt.question_id, staff_id=staff_id, message="Too late"
        )
