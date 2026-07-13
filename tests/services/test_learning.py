"""Sequential lesson access tests."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Lesson,
    LessonMaterial,
)
from course_platform.models.enums import VideoSource
from course_platform.services.learning import LearningService
from course_platform.services.students import StudentRegistration, StudentService


async def test_current_lesson_matches_enrollment_position(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=777, first_name="Student")
    )

    async with session_factory() as session:
        course = Course(slug="sequential", title="Sequential course")
        cohort = Cohort(title="Main cohort")
        first_lesson = Lesson(position=1, title="First", is_published=True)
        first_lesson.assignment = Assignment(instructions="First homework")
        second_lesson = Lesson(position=2, title="Second", is_published=True)
        second_lesson.materials.extend(
            [
                LessonMaterial(
                    position=2,
                    title="Second video",
                    video_source=VideoSource.EXTERNAL_URL,
                    video_reference="https://vimeo.com/2",
                ),
                LessonMaterial(
                    position=1,
                    title="First video",
                    video_source=VideoSource.EXTERNAL_URL,
                    video_reference="https://vimeo.com/1",
                ),
            ]
        )
        course.cohorts.append(cohort)
        course.lessons.extend([first_lesson, second_lesson])
        session.add_all(
            [
                course,
                Enrollment(
                    student_id=student.student_id,
                    cohort=cohort,
                    current_lesson_position=2,
                ),
            ]
        )
        await session.commit()

    learning = LearningService(session_factory)
    lesson = await learning.get_current_lesson(777)
    outline = await learning.get_course_outline(777)

    assert lesson is not None
    assert lesson.position == 2
    assert lesson.title == "Second"
    assert lesson.total_lessons == 2
    assert lesson.assignment_instructions is None
    assert [material.title for material in lesson.materials] == [
        "First video",
        "Second video",
    ]
    assert outline is not None
    assert outline.total_lessons == 2
    assert [item.title for item in outline.lessons] == ["First", "Second"]
    assert [item.is_current for item in outline.lessons] == [False, True]


async def test_unpublished_current_lesson_is_not_returned(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=888, first_name="Student")
    )

    async with session_factory() as session:
        course = Course(slug="draft-course", title="Draft course")
        cohort = Cohort(title="Draft cohort")
        course.cohorts.append(cohort)
        course.lessons.append(Lesson(position=1, title="Draft", is_published=False))
        session.add_all([course, Enrollment(student_id=student.student_id, cohort=cohort)])
        await session.commit()

    assert await LearningService(session_factory).get_current_lesson(888) is None
