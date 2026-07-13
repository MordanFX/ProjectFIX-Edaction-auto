"""Lesson progress state and unlock rule tests."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import Cohort, Course, Enrollment, Lesson, LessonProgress
from course_platform.models.enums import LessonProgressStatus, UnlockRule
from course_platform.services.learning import LearningService
from course_platform.services.progression import ProgressionService
from course_platform.services.students import StudentRegistration, StudentService
from course_platform.services.submissions import SubmissionService


async def test_submission_rule_advances_and_records_both_lessons(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=501, first_name="Submission")
    )
    await seed_demo_data(session_factory)
    async with session_factory() as session:
        course = await session.scalar(select(Course))
        assert course is not None
        course.unlock_rule = UnlockRule.AFTER_SUBMISSION
        await session.commit()

    submissions = SubmissionService(session_factory)
    await ProgressionService(session_factory).mark_current_viewed(501)
    await submissions.begin(501)
    await submissions.submit_text(501, "Done")

    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))
        progress = list(
            await session.scalars(
                select(LessonProgress)
                .join(Lesson, Lesson.id == LessonProgress.lesson_id)
                .order_by(Lesson.position)
            )
        )

    assert enrollment is not None
    assert enrollment.current_lesson_position == 2
    assert [item.status for item in progress] == [
        LessonProgressStatus.COMPLETED,
        LessonProgressStatus.AVAILABLE,
    ]
    assert progress[0].homework_submitted_at is not None


async def test_view_rule_advances_without_homework(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=502, first_name="Viewer")
    )
    async with session_factory() as session:
        course = Course(
            slug="view-course",
            title="View course",
            unlock_rule=UnlockRule.AFTER_VIEW,
        )
        course.lessons.extend(
            [
                Lesson(position=1, title="First", is_published=True),
                Lesson(position=2, title="Second", is_published=True),
            ]
        )
        course.cohorts.append(cohort := Cohort(title="View cohort"))
        session.add_all([course, Enrollment(student_id=student.student_id, cohort=cohort)])
        await session.commit()

    first = await LearningService(session_factory).get_current_lesson(502)
    result = await ProgressionService(session_factory).mark_current_viewed(502)
    second = await LearningService(session_factory).get_current_lesson(502)

    assert first is not None and first.position == 1
    assert result.status is LessonProgressStatus.COMPLETED
    assert result.current_lesson_position == 2
    assert result.next_lesson_available is True
    assert second is not None and second.position == 2


async def test_release_offset_keeps_lesson_locked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=503, first_name="Scheduled")
    )
    async with session_factory() as session:
        course = Course(slug="scheduled-course", title="Scheduled course")
        course.lessons.append(
            Lesson(
                position=1,
                title="Tomorrow",
                is_published=True,
                release_offset_hours=24,
            )
        )
        course.cohorts.append(cohort := Cohort(title="Scheduled cohort"))
        session.add_all([course, Enrollment(student_id=student.student_id, cohort=cohort)])
        await session.commit()

    lesson = await LearningService(session_factory).get_current_lesson(503)
    async with session_factory() as session:
        progress = await session.scalar(select(LessonProgress))

    assert lesson is None
    assert progress is not None
    assert progress.status is LessonProgressStatus.LOCKED
    assert progress.release_at is not None
    assert progress.available_at is None
