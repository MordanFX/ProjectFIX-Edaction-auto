"""Shared curator review workflow tests."""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import (
    Enrollment,
    Feedback,
    FeedbackAttachment,
    StaffUser,
    Student,
    Submission,
)
from course_platform.models.enums import (
    AttachmentKind,
    EnrollmentStatus,
    FeedbackVerdict,
    StaffRole,
    SubmissionStatus,
)
from course_platform.services.access_scope import StaffScope
from course_platform.services.progression import ProgressionService
from course_platform.services.reviews import (
    FeedbackAttachmentInput,
    ReviewService,
    SubmissionAlreadyReviewedError,
    SubmissionNotFoundError,
    UnauthorizedReviewerError,
)
from course_platform.services.students import StudentRegistration, StudentService
from course_platform.services.submissions import SubmissionService


async def prepare_pending_submission(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    await StudentService(session_factory).register(
        StudentRegistration(
            telegram_user_id=111,
            first_name="Demo",
            last_name="Student",
            username="demo_student",
        )
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(111)
    submissions = SubmissionService(session_factory)
    await submissions.begin(111)
    await submissions.submit_text(111, "Homework result")

    async with session_factory() as session:
        submission_id = await session.scalar(select(Submission.id))
        session.add(
            StaffUser(
                login="curator",
                display_name="Demo Curator",
                telegram_user_id=222,
            )
        )
        await session.commit()

    assert submission_id is not None
    return submission_id


async def test_pending_queue_contains_student_and_work_details(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)

    queue = await ReviewService(session_factory).list_pending()

    assert len(queue) == 1
    assert queue[0].submission_id == submission_id
    assert queue[0].student_name == "Demo Student"
    assert queue[0].student_username == "demo_student"
    assert queue[0].lesson_position == 1
    assert queue[0].text_body == "Homework result"
    assert queue[0].attachment_count == 0


async def test_accepting_submission_records_feedback_and_opens_next_lesson(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    result = await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.ACCEPTED,
        message="  Отличная работа.  ",
    )

    async with session_factory() as session:
        submission = await session.get(Submission, submission_id)
        feedback = await session.scalar(select(Feedback))
        enrollment = await session.scalar(select(Enrollment))

    assert submission is not None
    assert submission.status is SubmissionStatus.ACCEPTED
    assert submission.reviewed_at is not None
    assert feedback is not None
    assert feedback.message == "Отличная работа."
    assert enrollment is not None
    assert enrollment.current_lesson_position == 2
    assert enrollment.status is EnrollmentStatus.ACTIVE
    assert result.student_telegram_user_id == 111
    assert result.current_lesson_position == 2
    assert result.course_completed is False


async def test_revision_request_keeps_current_lesson_and_leaves_queue(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    result = await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.REVISION_REQUESTED,
        message="Добавь больше деталей.",
    )

    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))

    assert result.verdict is FeedbackVerdict.REVISION_REQUESTED
    assert enrollment is not None
    assert enrollment.current_lesson_position == 1
    assert await reviews.list_pending() == []
    history = await reviews.list_pending(include_reviewed=True)
    assert len(history) == 1
    assert history[0].submission_id == submission_id
    assert history[0].status is SubmissionStatus.REVISION_REQUESTED


async def test_detail_includes_previous_attempt_and_curator_feedback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)
    await reviews.review(
        submission_id=first_submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.REVISION_REQUESTED,
        message="Explain the calculation",
    )

    submissions = SubmissionService(session_factory)
    await submissions.begin(111)
    await submissions.submit_text(111, "Updated homework result")
    async with session_factory() as session:
        second_submission_id = await session.scalar(
            select(Submission.id)
            .where(Submission.attempt_number == 2)
        )

    assert second_submission_id is not None
    detail = await reviews.get_detail(second_submission_id)

    assert detail.attempt_number == 2
    assert len(detail.previous_attempts) == 1
    previous = detail.previous_attempts[0]
    assert previous.submission_id == first_submission_id
    assert previous.attempt_number == 1
    assert previous.text_body == "Homework result"
    assert previous.feedback_verdict is FeedbackVerdict.REVISION_REQUESTED
    assert previous.feedback_message == "Explain the calculation"


async def test_telegram_feedback_draft_survives_until_comment_is_sent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    pending = await reviews.begin_telegram_feedback(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.REVISION_REQUESTED,
        source_chat_id=222,
        source_message_id=77,
    )
    restored = await reviews.get_pending_telegram_feedback(222)

    assert restored == pending
    completion = await reviews.complete_telegram_feedback(
        reviewer_telegram_user_id=222,
        message="Добавь пояснение к последнему шагу.",
    )

    async with session_factory() as session:
        feedback = await session.scalar(select(Feedback))

    assert completion.result.verdict is FeedbackVerdict.REVISION_REQUESTED
    assert completion.source_message_id == 77
    assert feedback is not None
    assert feedback.message == "Добавь пояснение к последнему шагу."
    assert await reviews.get_pending_telegram_feedback(222) is None


async def test_curator_feedback_can_include_attachment_without_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    result = await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.REVISION_REQUESTED,
        message=" ",
        attachments=(
            FeedbackAttachmentInput(
                kind=AttachmentKind.PHOTO,
                telegram_file_id="file-id",
                telegram_file_unique_id="unique-id",
                source_chat_id=222,
                source_message_id=88,
                mime_type="image/jpeg",
                file_size=12345,
                width=1280,
                height=720,
            ),
        ),
    )

    async with session_factory() as session:
        feedback = await session.scalar(select(Feedback))
        attachment = await session.scalar(select(FeedbackAttachment))

    detail = await reviews.get_detail(submission_id)

    assert result.feedback_attachment_count == 1
    assert feedback is not None
    assert feedback.message == "См. вложение куратора."
    assert attachment is not None
    assert attachment.kind is AttachmentKind.PHOTO
    assert attachment.source_chat_id == 222
    assert attachment.source_message_id == 88
    assert len(detail.feedback_attachments) == 1
    assert detail.feedback_attachments[0].kind is AttachmentKind.PHOTO
    assert detail.feedback_attachments[0].source_available is True


async def test_panel_uploaded_feedback_attachment_is_available_in_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Web-panel uploads only set local_path (no Telegram source_chat_id)."""
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.REVISION_REQUESTED,
        message="Исправь, пожалуйста",
        attachments=(
            FeedbackAttachmentInput(
                kind=AttachmentKind.PHOTO,
                local_path="data/feedback_uploads/example.png",
                file_name="Скриншот.png",
                mime_type="image/png",
                file_size=12345,
            ),
        ),
    )

    detail = await reviews.get_detail(submission_id)
    assert len(detail.feedback_attachments) == 1
    assert detail.feedback_attachments[0].source_available is True


async def test_feedback_attachment_with_only_telegram_file_id_is_available(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Older/partial feedback rows can still be opened through Telegram file_id."""
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.ACCEPTED,
        message="РџСЂРёРЅСЏС‚Рѕ",
        attachments=(
            FeedbackAttachmentInput(
                kind=AttachmentKind.PHOTO,
                telegram_file_id="telegram-feedback-photo",
                telegram_file_unique_id="telegram-feedback-photo-unique",
                file_name="РЎРєСЂРёРЅС€РѕС‚.png",
                mime_type="image/png",
                file_size=44_000,
            ),
        ),
    )

    detail = await reviews.get_detail(submission_id)

    assert len(detail.feedback_attachments) == 1
    assert detail.feedback_attachments[0].source_available is True


async def test_only_active_staff_can_review_and_decision_is_final(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    with pytest.raises(UnauthorizedReviewerError):
        await reviews.review(
            submission_id=submission_id,
            reviewer_telegram_user_id=999,
            verdict=FeedbackVerdict.ACCEPTED,
            message="Unauthorized",
        )

    await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=222,
        verdict=FeedbackVerdict.ACCEPTED,
        message="Accepted",
    )
    with pytest.raises(SubmissionAlreadyReviewedError):
        await reviews.review(
            submission_id=submission_id,
            reviewer_telegram_user_id=222,
            verdict=FeedbackVerdict.ACCEPTED,
            message="Second decision",
        )


async def test_student_pinned_to_curator_is_hidden_from_other_curators(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    submission_id = await prepare_pending_submission(session_factory)
    reviews = ReviewService(session_factory)

    async with session_factory() as session:
        curator_a = await session.scalar(
            select(StaffUser).where(StaffUser.telegram_user_id == 222)
        )
        assert curator_a is not None
        curator_b = StaffUser(login="curator-b", display_name="Curator B")
        admin = StaffUser(login="admin", display_name="Admin", role=StaffRole.ADMIN)
        session.add_all([curator_b, admin])
        await session.flush()
        student = await session.scalar(select(Student))
        assert student is not None
        student.assigned_curator_id = curator_b.id
        await session.commit()
        curator_a_id = curator_a.id
        curator_b_id = curator_b.id
        admin_id = admin.id

    scope_a = StaffScope(staff_id=curator_a_id, is_admin=False)
    scope_b = StaffScope(staff_id=curator_b_id, is_admin=False)
    scope_admin = StaffScope(staff_id=admin_id, is_admin=True)

    assert await reviews.list_pending(viewer=scope_a) == []
    queue_b = await reviews.list_pending(viewer=scope_b)
    assert [item.submission_id for item in queue_b] == [submission_id]
    queue_admin = await reviews.list_pending(viewer=scope_admin)
    assert [item.submission_id for item in queue_admin] == [submission_id]

    with pytest.raises(SubmissionNotFoundError):
        await reviews.get_detail(submission_id, viewer=scope_a)
    detail_b = await reviews.get_detail(submission_id, viewer=scope_b)
    assert detail_b.submission_id == submission_id

    with pytest.raises(SubmissionNotFoundError):
        await reviews.assign_to_reviewer(submission_id=submission_id, reviewer_id=curator_a_id)
    claimed = await reviews.assign_to_reviewer(
        submission_id=submission_id, reviewer_id=curator_b_id
    )
    assert claimed.assigned_reviewer_id == curator_b_id
