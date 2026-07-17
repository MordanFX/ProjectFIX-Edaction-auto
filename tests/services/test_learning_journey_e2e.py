"""End-to-end coverage for the complete student and curator journey."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import Enrollment, Submission
from course_platform.models.enums import EnrollmentStatus, FeedbackVerdict, SubmissionStatus
from course_platform.services.notifications import FeedbackNotificationService
from course_platform.services.progression import ProgressionService
from course_platform.services.reviews import ReviewService
from course_platform.services.students import StudentRegistration, StudentService, StudentStage
from course_platform.services.submissions import SubmissionService


async def test_complete_course_journey_keeps_feedback_stages_correct(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    telegram_user_id = 900
    students = StudentService(session_factory)
    await students.register(
        StudentRegistration(
            telegram_user_id=telegram_user_id,
            first_name="E2E",
            last_name="Student",
            username="e2e_student",
        )
    )
    await seed_demo_data(session_factory)

    progression = ProgressionService(session_factory)
    submissions = SubmissionService(session_factory)
    reviews = ReviewService(session_factory)

    for lesson_position in range(1, 4):
        journey = await students.get_journey(telegram_user_id)
        assert journey is not None
        assert journey.lesson_position == lesson_position
        assert journey.stage is StudentStage.NEEDS_VIEW

        await progression.mark_current_viewed(telegram_user_id)
        assert (await students.get_journey(telegram_user_id)).stage is StudentStage.READY_TO_SUBMIT

        await submissions.begin(telegram_user_id)
        await submissions.submit_text(
            telegram_user_id,
            f"Результат домашнего задания {lesson_position}",
        )
        assert (await students.get_journey(telegram_user_id)).stage is StudentStage.AWAITING_REVIEW

        async with session_factory() as session:
            submission_id = await session.scalar(
                select(Submission.id)
                .where(Submission.status == SubmissionStatus.SUBMITTED)
                .order_by(Submission.created_at.desc())
                .limit(1)
            )
        assert submission_id is not None
        result = await reviews.review(
            submission_id=submission_id,
            reviewer_telegram_user_id=telegram_user_id,
            verdict=FeedbackVerdict.ACCEPTED,
            message=f"Урок {lesson_position} принят",
        )
        assert result.course_completed is (lesson_position == 3)

    final_journey = await students.get_journey(telegram_user_id)
    assert final_journey is not None
    assert final_journey.stage is StudentStage.COURSE_COMPLETED

    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))
    assert enrollment is not None
    assert enrollment.status is EnrollmentStatus.COMPLETED

    delayed_notifications = await FeedbackNotificationService(session_factory).list_pending()
    assert len(delayed_notifications) == 3
    assert [item.course_completed for item in delayed_notifications] == [False, False, True]


async def test_completed_lesson_without_advance_reads_as_locked_stage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    telegram_user_id = 901
    students = StudentService(session_factory)
    await students.register(
        StudentRegistration(telegram_user_id=telegram_user_id, first_name="Blocked")
    )
    await seed_demo_data(session_factory)

    progression = ProgressionService(session_factory)
    submissions = SubmissionService(session_factory)
    reviews = ReviewService(session_factory)

    await progression.mark_current_viewed(telegram_user_id)
    await submissions.begin(telegram_user_id)
    await submissions.submit_text(telegram_user_id, "Ответ на первый урок")
    async with session_factory() as session:
        submission_id = await session.scalar(select(Submission.id).limit(1))
    assert submission_id is not None
    await reviews.review(
        submission_id=submission_id,
        reviewer_telegram_user_id=telegram_user_id,
        verdict=FeedbackVerdict.ACCEPTED,
        message="Принято",
    )

    # The next lesson is not released yet: the enrollment stays on the
    # completed lesson instead of advancing to an open one.
    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))
        assert enrollment is not None
        enrollment.current_lesson_position = 1
        await session.commit()

    journey = await students.get_journey(telegram_user_id)
    assert journey is not None
    assert journey.stage is StudentStage.LESSON_LOCKED
