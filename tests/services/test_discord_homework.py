"""Discord homework persistence tests."""

from course_platform.services.discord_homework import DiscordHomeworkService
from course_platform.services.students import StudentRegistration, StudentService


async def test_remembers_one_homework_space_per_guild_user(session_factory) -> None:
    service = DiscordHomeworkService(session_factory)
    student = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=1, first_name="Student")
    )

    saved = await service.remember(
        guild_id=100,
        discord_user_id=200,
        parent_channel_id=300,
        channel_id=400,
        channel_name="dz-student-0200",
        kind="private_thread",
        display_name="Student",
        student_id=student.student_id,
    )
    found = await service.find(100, 200)

    assert found == saved
    assert saved.student_id == student.student_id
    assert saved.channel_name == "dz-student-0200"
    assert await service.find(100, 201) is None
