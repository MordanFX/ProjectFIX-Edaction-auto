"""Create repeatable demonstration course data for local development."""

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from course_platform.config import get_settings
from course_platform.db.session import create_engine, create_session_factory, session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    CourseReminderStep,
    Enrollment,
    Lesson,
    StaffUser,
    Student,
)
from course_platform.models.enums import (
    EnrollmentStatus,
    ReminderKind,
    SubmissionKind,
    VideoSource,
)
from course_platform.services.progression import ProgressionService

DEMO_COURSE_SLUG = "demo-learning-course"
DEMO_COHORT_TITLE = "Демонстрационный поток"
DEMO_CURATOR_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Bn8QCKrVyz+6p0qMIG0dYg$"
    "ZovJDE8xeFzJ1pHCeFP2x2fJqM50bz6DnlCJAFqDXvM"
)

DEMO_LESSONS = (
    (
        "Знакомство с курсом",
        "Разбираем структуру обучения и порядок прохождения уроков.",
        "Кратко опиши, какой результат хочешь получить от курса.",
        SubmissionKind.ANY,
    ),
    (
        "Первый практический блок",
        "Демонстрационный урок для проверки последовательной выдачи материалов.",
        "Пришли текст или файл с результатом первого практического задания.",
        SubmissionKind.ANY,
    ),
    (
        "Итоговая практика",
        "Закрепляем пройденное и оцениваем итоговый прогресс.",
        "Опиши результат и приложи итоговую работу.",
        SubmissionKind.ANY,
    ),
)

DEMO_REMINDER_STEPS = (
    (
        1,
        24,
        ReminderKind.STUDENT_GENTLE,
        "Урок «{lesson_title}» ждёт тебя. Вернись к материалу, когда будет удобно.",
    ),
    (
        2,
        48,
        ReminderKind.STUDENT_FOLLOW_UP,
        "Ты ещё не отметил урок «{lesson_title}» просмотренным. Продолжим обучение?",
    ),
    (
        3,
        72,
        ReminderKind.CURATOR_ALERT,
        "Ученик давно не возвращался к уроку.",
    ),
)


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    course_created: bool
    lessons_created: int
    enrollments_created: int
    reviewer_created: bool


async def seed_demo_data(
    session_factory: async_sessionmaker[AsyncSession],
) -> DemoSeedResult:
    """Create missing demo records and enroll active students exactly once."""

    async with session_scope(session_factory) as session:
        course = await session.scalar(select(Course).where(Course.slug == DEMO_COURSE_SLUG))
        course_created = course is None
        if course is None:
            course = Course(
                slug=DEMO_COURSE_SLUG,
                title="Демонстрационный учебный курс",
                description="Временные материалы для проверки механики Telegram-бота.",
            )
            session.add(course)
            await session.flush()

        existing_reminder_steps = {
            step.sequence: step
            for step in await session.scalars(
                select(CourseReminderStep).where(CourseReminderStep.course_id == course.id)
            )
        }
        for sequence, delay_hours, kind, message_text in DEMO_REMINDER_STEPS:
            step = existing_reminder_steps.get(sequence)
            if step is None:
                step = CourseReminderStep(course_id=course.id, sequence=sequence)
                session.add(step)
            step.delay_hours = delay_hours
            step.kind = kind
            step.message_text = message_text
            step.is_active = True

        cohort = await session.scalar(
            select(Cohort).where(
                Cohort.course_id == course.id,
                Cohort.title == DEMO_COHORT_TITLE,
            )
        )
        if cohort is None:
            cohort = Cohort(course=course, title=DEMO_COHORT_TITLE)
            session.add(cohort)
            await session.flush()

        existing_lessons = {
            lesson.position: lesson
            for lesson in await session.scalars(
                select(Lesson)
                .options(selectinload(Lesson.assignment))
                .where(Lesson.course_id == course.id)
            )
        }
        lessons_created = 0
        for position, lesson_data in enumerate(DEMO_LESSONS, start=1):
            title, description, instructions, submission_kind = lesson_data
            lesson = existing_lessons.get(position)
            if lesson is None:
                lesson = Lesson(course=course, position=position, title=title)
                session.add(lesson)
                lessons_created += 1

            lesson.title = title
            lesson.description = description
            lesson.video_source = VideoSource.PLACEHOLDER
            lesson.is_published = True
            if lesson.assignment is None:
                lesson.assignment = Assignment(instructions=instructions)
            lesson.assignment.instructions = instructions
            lesson.assignment.submission_kind = submission_kind

        enrolled_student_ids = set(
            await session.scalars(
                select(Enrollment.student_id).where(Enrollment.cohort_id == cohort.id)
            )
        )
        active_student_ids = set(
            await session.scalars(select(Student.id).where(Student.is_active.is_(True)))
        )
        missing_student_ids = active_student_ids - enrolled_student_ids
        session.add_all(
            [Enrollment(student_id=student_id, cohort=cohort) for student_id in missing_student_ids]
        )

        demo_student = await session.scalar(
            select(Student).where(Student.is_active.is_(True)).order_by(Student.created_at).limit(1)
        )
        demo_reviewer = await session.scalar(
            select(StaffUser).where(StaffUser.login == "demo-curator")
        )
        reviewer_created = demo_reviewer is None and demo_student is not None
        if demo_reviewer is None and demo_student is not None:
            demo_reviewer = StaffUser(
                login="demo-curator",
                display_name="Демонстрационный куратор",
                password_hash=DEMO_CURATOR_PASSWORD_HASH,
                telegram_user_id=demo_student.telegram_user_id,
            )
            session.add(demo_reviewer)
        elif demo_reviewer is not None and demo_student is not None:
            demo_reviewer.telegram_user_id = demo_student.telegram_user_id
            demo_reviewer.password_hash = DEMO_CURATOR_PASSWORD_HASH
            demo_reviewer.is_active = True

        await session.flush()
        enrollment_lessons = await session.execute(
            select(Enrollment, Lesson)
            .join(Cohort, Cohort.id == Enrollment.cohort_id)
            .join(
                Lesson,
                (Lesson.course_id == Cohort.course_id)
                & (Lesson.position == Enrollment.current_lesson_position),
            )
            .where(
                Enrollment.status == EnrollmentStatus.ACTIVE,
                Lesson.is_published.is_(True),
            )
        )
        for enrollment, lesson in enrollment_lessons:
            await ProgressionService.ensure_current_available(
                session,
                enrollment=enrollment,
                lesson=lesson,
            )

        return DemoSeedResult(
            course_created=course_created,
            lessons_created=lessons_created,
            enrollments_created=len(missing_student_ids),
            reviewer_created=reviewer_created,
        )


async def run_seed() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise SystemExit("Demo seed is disabled in production")

    engine = create_engine(settings)
    try:
        result = await seed_demo_data(create_session_factory(engine))
    finally:
        await engine.dispose()

    print(
        "Demo seed complete: "
        f"course_created={result.course_created}, "
        f"lessons_created={result.lessons_created}, "
        f"enrollments_created={result.enrollments_created}, "
        f"reviewer_created={result.reviewer_created}"
    )


if __name__ == "__main__":
    asyncio.run(run_seed())
