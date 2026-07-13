"""Database-backed feedback notification tests."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import Cohort, Course, Enrollment, Feedback, StaffUser, Submission
from course_platform.models.enums import (
    CourseAudience,
    EnrollmentStatus,
    FeedbackVerdict,
    NotificationStatus,
)
from course_platform.services.notifications import (
    AccessNotificationService,
    FeedbackNotificationService,
)
from course_platform.services.progression import ProgressionService
from course_platform.services.reviews import ReviewService
from course_platform.services.students import StudentRegistration, StudentService
from course_platform.services.submissions import SubmissionService


async def create_pending_notification(
    session_factory: async_sessionmaker[AsyncSession],
) -> Feedback:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=101, first_name="Student")
    )
    await seed_demo_data(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(101)
    submissions = SubmissionService(session_factory)
    await submissions.begin(101)
    await submissions.submit_text(101, "Homework")

    async with session_factory() as session:
        submission_id = await session.scalar(select(Submission.id))
        reviewer = await session.scalar(select(StaffUser))
    assert submission_id is not None
    assert reviewer is not None

    await ReviewService(session_factory).review_by_staff_id(
        submission_id=submission_id,
        reviewer_id=reviewer.id,
        verdict=FeedbackVerdict.ACCEPTED,
        message="Accepted from web panel",
    )
    async with session_factory() as session:
        feedback = await session.scalar(select(Feedback))
    assert feedback is not None
    return feedback


async def test_feedback_is_retried_then_marked_sent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    feedback = await create_pending_notification(session_factory)
    notifications = FeedbackNotificationService(session_factory)

    pending = await notifications.list_pending()
    assert len(pending) == 1
    assert pending[0].student_telegram_user_id == 101
    assert pending[0].message == "Accepted from web panel"
    assert pending[0].current_lesson_position == 2

    await notifications.mark_failed(feedback.id, "temporary error")
    assert len(await notifications.list_pending()) == 1
    await notifications.mark_sent(feedback.id)

    async with session_factory() as session:
        stored_feedback = await session.get(Feedback, feedback.id)

    assert await notifications.list_pending() == []
    assert stored_feedback is not None
    assert stored_feedback.notification_status is NotificationStatus.SENT
    assert stored_feedback.notification_attempts == 2
    assert stored_feedback.notified_at is not None
    assert stored_feedback.notification_error is None


async def test_access_notification_is_marked_sent_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    registration = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=202, first_name="Student")
    )
    async with session_factory() as session:
        course = Course(
            slug="practice-access",
            title="Practice",
            description=None,
            audience=CourseAudience.TELEGRAM,
            is_active=True,
        )
        cohort = Cohort(course=course, title="Main")
        enrollment = Enrollment(
            student_id=registration.student_id,
            cohort=cohort,
            status=EnrollmentStatus.ACTIVE,
            current_lesson_position=1,
        )
        session.add_all([course, cohort, enrollment])
        await session.commit()
        enrollment_id = enrollment.id

    notifications = AccessNotificationService(session_factory)

    pending = await notifications.list_pending()
    assert len(pending) == 1
    assert pending[0].enrollment_id == enrollment_id
    assert pending[0].student_telegram_user_id == 202
    assert pending[0].course_title == "Practice"

    await notifications.mark_sent(enrollment_id)

    assert await notifications.list_pending() == []
