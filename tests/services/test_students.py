"""Student registration and progress service tests."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Lesson,
    Student,
    Submission,
)
from course_platform.models.enums import AccessType, EnrollmentStatus, SubmissionStatus
from course_platform.services.students import (
    InvalidQuietHoursError,
    InvalidTimezoneError,
    StudentAccessService,
    StudentRegistration,
    StudentService,
)


def student_registration(*, first_name: str = "Student") -> StudentRegistration:
    return StudentRegistration(
        telegram_user_id=123456,
        first_name=first_name,
        username="student_user",
        language_code="uk",
    )


async def test_register_creates_and_then_updates_one_student(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = StudentService(session_factory)

    first_result = await service.register(student_registration())
    second_result = await service.register(student_registration(first_name="Updated"))

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Student))
        student = await session.scalar(select(Student))

    assert first_result.is_new is True
    assert second_result.is_new is False
    assert first_result.student_id == second_result.student_id
    assert count == 1
    assert student is not None
    assert student.first_name == "Updated"


async def test_progress_is_none_without_enrollment(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = StudentService(session_factory)
    await service.register(student_registration())

    assert await service.get_progress(123456) is None


async def test_student_can_update_notification_settings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = StudentService(session_factory)
    await service.register(student_registration())

    journey = await service.update_settings(
        123456,
        timezone="Europe/Warsaw",
        quiet_hours=(23, 8),
        reminders_enabled=False,
    )

    assert journey is not None
    assert journey.timezone == "Europe/Warsaw"
    assert (journey.quiet_hours_start, journey.quiet_hours_end) == (23, 8)
    assert journey.reminders_enabled is False


async def test_student_settings_reject_invalid_values(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = StudentService(session_factory)
    await service.register(student_registration())

    with pytest.raises(InvalidTimezoneError):
        await service.update_settings(123456, timezone="Invalid/Timezone")
    with pytest.raises(InvalidQuietHoursError):
        await service.update_settings(123456, quiet_hours=(24, 8))


async def test_progress_counts_lessons_assignments_and_accepted_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = StudentService(session_factory)
    registration = await service.register(student_registration())

    async with session_factory() as session:
        course = Course(slug="practical-course", title="Practical course")
        cohort = Cohort(title="Summer")
        first_lesson = Lesson(position=1, title="First")
        first_assignment = Assignment(instructions="First task")
        first_lesson.assignment = first_assignment
        second_lesson = Lesson(position=2, title="Second")
        course.cohorts.append(cohort)
        course.lessons.extend([first_lesson, second_lesson])
        enrollment = Enrollment(student_id=registration.student_id, cohort=cohort)
        session.add_all([course, enrollment])
        await session.flush()
        session.add(
            Submission(
                enrollment=enrollment,
                assignment=first_assignment,
                status=SubmissionStatus.ACCEPTED,
            )
        )
        await session.commit()

    progress = await service.get_progress(123456)

    assert progress is not None
    assert progress.course_title == "Practical course"
    assert progress.current_lesson_position == 1
    assert progress.total_lessons == 2
    assert progress.total_assignments == 1
    assert progress.accepted_submissions == 1


async def test_admin_can_update_student_access(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = StudentService(session_factory)
    registration = await service.register(student_registration())

    async with session_factory() as session:
        course = Course(slug="access-course", title="Access course")
        cohort = Cohort(title="Access cohort")
        course.cohorts.append(cohort)
        session.add(course)
        await session.commit()
        cohort_id = cohort.id

    access_service = StudentAccessService(session_factory)
    detail = await access_service.update_enrollment(
        student_id=registration.student_id,
        cohort_id=cohort_id,
        status=EnrollmentStatus.PAUSED,
        access_type=AccessType.TRIAL,
        current_lesson_position=2,
    )

    assert detail.enrollment_status == EnrollmentStatus.PAUSED
    assert detail.access_type == AccessType.TRIAL
    assert detail.cohort_id == cohort_id
    assert detail.current_lesson_position == 2
