"""Create one pending homework item for visual review of the local admin panel."""

import asyncio

from sqlalchemy import select

from course_platform.config import get_settings
from course_platform.db.session import create_engine, create_session_factory
from course_platform.models import Student
from course_platform.services.submissions import SubmissionPendingError, SubmissionService


async def create_demo_submission() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise SystemExit("Demo submissions are disabled in production")

    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            telegram_user_id = await session.scalar(
                select(Student.telegram_user_id).order_by(Student.created_at).limit(1)
            )
        if telegram_user_id is None:
            raise SystemExit("Run the demo seed after registering a student first")

        submissions = SubmissionService(session_factory)
        try:
            prompt = await submissions.begin(telegram_user_id)
        except SubmissionPendingError:
            print("A demo submission is already pending")
            return
        receipt = await submissions.submit_text(
            telegram_user_id,
            "Выполнил практическое задание и описал основные шаги решения. "
            "Готов получить обратную связь по структуре работы.",
        )
        print(
            f"Demo submission created: lesson={prompt.lesson_position}, "
            f"attempt={receipt.attempt_number}"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_demo_submission())
