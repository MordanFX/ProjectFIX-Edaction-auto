"""Persistent text homework workflow tests."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import Assignment, StudentBotState, Submission, SubmissionAttachment
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
    NotAwaitingSubmissionError,
    SubmissionPendingError,
    SubmissionService,
    UnsupportedSubmissionKindError,
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
