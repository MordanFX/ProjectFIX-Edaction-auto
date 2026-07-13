"""Create local-only submissions used to preview the curator review interface."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.config import get_settings
from course_platform.db.session import create_engine, create_session_factory, session_scope
from course_platform.dev.seed_demo import DEMO_COHORT_TITLE, DEMO_COURSE_SLUG, seed_demo_data
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Lesson,
    Student,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import AttachmentKind, SubmissionStatus
from course_platform.services.progression import ProgressionService


@dataclass(frozen=True, slots=True)
class ShowcaseStudent:
    telegram_user_id: int
    username: str
    first_name: str
    last_name: str
    text: str
    lesson_position: int = 1
    create_submission: bool = True
    attachment_kind: AttachmentKind | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None


SHOWCASE_STUDENTS = (
    ShowcaseStudent(
        telegram_user_id=9_100_000_001,
        username="alina_moroz",
        first_name="Алина",
        last_name="Мороз",
        text=(
            "Записала экран и показала весь процесс выполнения задания. "
            "В конце добавила короткий разбор результата."
        ),
        attachment_kind=AttachmentKind.VIDEO,
        file_name="lesson-01-screen-recording.mp4",
        mime_type="video/mp4",
        file_size=51_064_832,
        duration_seconds=84,
        width=1920,
        height=1080,
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_002,
        username="max_orlov",
        first_name="Максим",
        last_name="Орлов",
        text=(
            "Подготовил первый вариант работы и приложил PDF. "
            "Особенно нужен комментарий по структуре второго блока."
        ),
        attachment_kind=AttachmentKind.DOCUMENT,
        file_name="homework-first-draft.pdf",
        mime_type="application/pdf",
        file_size=2_516_582,
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_003,
        username="sofia_levchenko",
        first_name="София",
        last_name="Левченко",
        text="Мой результат после первого урока. Сделала два варианта и выбрала этот как основной.",
        attachment_kind=AttachmentKind.PHOTO,
        file_name="homework-result.jpg",
        mime_type="image/jpeg",
        file_size=1_835_008,
        width=1440,
        height=1920,
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_004,
        username="dmitry_volkov",
        first_name="Дмитрий",
        last_name="Волков",
        lesson_position=2,
        text=(
            "Разобрал практический блок по шагам. Сначала описал исходные данные, "
            "затем показал решение и отдельно сформулировал выводы."
        ),
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_005,
        username="elena_romanova",
        first_name="Елена",
        last_name="Романова",
        lesson_position=2,
        text="Прикладываю короткую запись экрана с пояснением ключевых действий.",
        attachment_kind=AttachmentKind.VIDEO,
        file_name="practice-block-demo.mp4",
        mime_type="video/mp4",
        file_size=12_845_056,
        duration_seconds=47,
        width=1280,
        height=720,
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_006,
        username="artem_kovalenko",
        first_name="Артём",
        last_name="Коваленко",
        lesson_position=3,
        text="Итоговую работу оформил в одном документе: результат, пояснения и самооценка.",
        attachment_kind=AttachmentKind.DOCUMENT,
        file_name="final-homework.pdf",
        mime_type="application/pdf",
        file_size=4_308_992,
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_007,
        username="maria_kim",
        first_name="Мария",
        last_name="Ким",
        text="Собрала финальный вариант макета. Хотелось бы получить комментарий по композиции.",
        attachment_kind=AttachmentKind.PHOTO,
        file_name="layout-result.jpg",
        mime_type="image/jpeg",
        file_size=2_097_152,
        width=1920,
        height=1080,
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_008,
        username="nikita_bely",
        first_name="Никита",
        last_name="Белый",
        lesson_position=3,
        text=(
            "Завершил итоговую практику. Основной результат получил, но не уверен, "
            "что достаточно подробно описал второй этап."
        ),
    ),
    ShowcaseStudent(
        telegram_user_id=9_100_000_009,
        username="olga_novikova",
        first_name="Ольга",
        last_name="Новикова",
        text="",
        create_submission=False,
    ),
)


async def seed_review_showcase(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    await seed_demo_data(session_factory)
    created = 0
    async with session_scope(session_factory) as session:
        course = await session.scalar(select(Course).where(Course.slug == DEMO_COURSE_SLUG))
        if course is None:
            raise RuntimeError("Demo course was not created")
        cohort = await session.scalar(
            select(Cohort).where(
                Cohort.course_id == course.id,
                Cohort.title == DEMO_COHORT_TITLE,
            )
        )
        lesson_rows = await session.execute(
            select(Lesson, Assignment)
            .join(Assignment, Assignment.lesson_id == Lesson.id)
            .where(Lesson.course_id == course.id)
        )
        lessons = {
            lesson.position: (lesson, assignment) for lesson, assignment in lesson_rows
        }
        if cohort is None or not lessons:
            raise RuntimeError("Demo cohort or lessons are missing")

        now = datetime.now(UTC)
        for index, showcase in enumerate(SHOWCASE_STUDENTS):
            lesson_data = lessons.get(showcase.lesson_position)
            if lesson_data is None:
                raise RuntimeError(f"Demo lesson {showcase.lesson_position} is missing")
            lesson, assignment = lesson_data
            student = await session.scalar(
                select(Student).where(Student.telegram_user_id == showcase.telegram_user_id)
            )
            if student is None:
                student = Student(
                    telegram_user_id=showcase.telegram_user_id,
                    username=showcase.username,
                    first_name=showcase.first_name,
                    last_name=showcase.last_name,
                    language_code="ru",
                )
                session.add(student)
                await session.flush()

            enrollment = await session.scalar(
                select(Enrollment).where(
                    Enrollment.student_id == student.id,
                    Enrollment.cohort_id == cohort.id,
                )
            )
            if enrollment is None:
                enrollment = Enrollment(student_id=student.id, cohort_id=cohort.id)
                session.add(enrollment)
                await session.flush()
            enrollment.current_lesson_position = lesson.position

            if not showcase.create_submission:
                await ProgressionService.ensure_current_available(
                    session,
                    enrollment=enrollment,
                    lesson=lesson,
                )
                continue

            pending = await session.scalar(
                select(Submission.id).where(
                    Submission.enrollment_id == enrollment.id,
                    Submission.assignment_id == assignment.id,
                    Submission.status.in_(
                        [SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW]
                    ),
                )
            )
            if pending is not None:
                await ProgressionService.record_submission(
                    session,
                    enrollment_id=enrollment.id,
                    lesson_id=lesson.id,
                    occurred_at=now,
                )
                continue

            latest_attempt = await session.scalar(
                select(Submission.attempt_number)
                .where(
                    Submission.enrollment_id == enrollment.id,
                    Submission.assignment_id == assignment.id,
                )
                .order_by(Submission.attempt_number.desc())
                .limit(1)
            )
            submission = Submission(
                enrollment_id=enrollment.id,
                assignment_id=assignment.id,
                attempt_number=(latest_attempt or 0) + 1,
                text_body=showcase.text,
                status=SubmissionStatus.SUBMITTED,
                submitted_at=now - timedelta(minutes=max(4, 68 - index * 8)),
            )
            if showcase.attachment_kind is not None:
                submission.attachments.append(
                    SubmissionAttachment(
                        kind=showcase.attachment_kind,
                        telegram_file_id=f"showcase-file-{showcase.telegram_user_id}",
                        telegram_file_unique_id=f"showcase-unique-{showcase.telegram_user_id}",
                        source_chat_id=showcase.telegram_user_id,
                        source_message_id=100 + index,
                        file_name=showcase.file_name,
                        mime_type=showcase.mime_type,
                        file_size=showcase.file_size,
                        duration_seconds=showcase.duration_seconds,
                        width=showcase.width,
                        height=showcase.height,
                    )
                )
            session.add(submission)
            await ProgressionService.record_submission(
                session,
                enrollment_id=enrollment.id,
                lesson_id=lesson.id,
                occurred_at=submission.submitted_at,
            )
            created += 1

    return created


async def run_seed() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise SystemExit("Showcase seed is disabled in production")
    engine = create_engine(settings)
    try:
        created = await seed_review_showcase(create_session_factory(engine))
    finally:
        await engine.dispose()
    print(f"Review showcase seed complete: submissions_created={created}")


if __name__ == "__main__":
    asyncio.run(run_seed())
