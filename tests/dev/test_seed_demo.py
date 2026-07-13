"""Idempotency tests for local demonstration data."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.api.security import verify_password
from course_platform.dev.seed_demo import seed_demo_data
from course_platform.models import Course, Enrollment, Lesson, StaffUser
from course_platform.services.students import StudentRegistration, StudentService


async def test_demo_seed_is_idempotent_and_enrolls_active_students(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=999, first_name="Demo Student")
    )

    first_result = await seed_demo_data(session_factory)
    second_result = await seed_demo_data(session_factory)

    async with session_factory() as session:
        course_count = await session.scalar(select(func.count()).select_from(Course))
        lesson_count = await session.scalar(select(func.count()).select_from(Lesson))
        enrollment_count = await session.scalar(select(func.count()).select_from(Enrollment))
        reviewer = await session.scalar(select(StaffUser))

    assert first_result.course_created is True
    assert first_result.lessons_created == 3
    assert first_result.enrollments_created == 1
    assert first_result.reviewer_created is True
    assert second_result.course_created is False
    assert second_result.lessons_created == 0
    assert second_result.enrollments_created == 0
    assert second_result.reviewer_created is False
    assert course_count == 1
    assert lesson_count == 3
    assert enrollment_count == 1
    assert reviewer is not None
    assert reviewer.password_hash is not None
    assert verify_password("demo-admin", reviewer.password_hash)
