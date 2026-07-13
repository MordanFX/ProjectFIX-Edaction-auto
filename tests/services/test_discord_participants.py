"""Independent Discord participant identity tests."""

from datetime import UTC, datetime

from sqlalchemy import select

from course_platform.models import DiscordHomeworkSpace, DiscordParticipant, Student
from course_platform.models.enums import StudentOrigin
from course_platform.services.discord_participants import DiscordParticipantService


async def test_creates_discord_profile_without_telegram_identity(session_factory) -> None:
    service = DiscordParticipantService(session_factory)

    first = await service.get_or_create(
        guild_id=10,
        discord_user_id=20,
        display_name="Discord Student",
        username="student.user",
        global_name="Discord Global",
        avatar_hash="avatar-one",
        guild_joined_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    second = await service.get_or_create(
        guild_id=10,
        discord_user_id=20,
        display_name="Renamed Student",
        username="renamed.user",
        global_name="Renamed Global",
        avatar_hash="avatar-two",
    )

    async with session_factory() as session:
        students = list(await session.scalars(select(Student)))
        participant = await session.scalar(select(DiscordParticipant))

    assert first.student_id == second.student_id
    assert len(students) == 1
    assert students[0].telegram_user_id is None
    assert students[0].origin is StudentOrigin.DISCORD
    assert students[0].first_name == "Renamed Student"
    assert participant is not None
    assert participant.username == "renamed.user"
    assert participant.global_name == "Renamed Global"
    assert participant.avatar_hash == "avatar-two"
    assert participant.guild_joined_at is not None
    assert participant.is_guild_member is True


async def test_tracks_private_space_activity_and_member_departure(session_factory) -> None:
    service = DiscordParticipantService(session_factory)
    participant = await service.get_or_create(
        guild_id=10,
        discord_user_id=20,
        display_name="Discord Student",
    )
    async with session_factory() as session:
        session.add(
            DiscordHomeworkSpace(
                guild_id=10,
                discord_user_id=20,
                student_id=participant.student_id,
                parent_channel_id=30,
                channel_id=40,
                channel_name="dz-discord-student-0020",
                kind="private_thread",
                display_name="Discord Student",
            )
        )
        await session.commit()

    assert await service.record_activity(
        guild_id=10,
        discord_user_id=20,
        display_name="Updated Student",
        username="updated",
        global_name=None,
        avatar_hash="new-avatar",
        guild_joined_at=None,
        channel_id=40,
    )
    assert not await service.record_activity(
        guild_id=10,
        discord_user_id=20,
        display_name="Wrong channel",
        username=None,
        global_name=None,
        avatar_hash=None,
        guild_joined_at=None,
        channel_id=41,
    )
    assert await service.mark_left(guild_id=10, discord_user_id=20)

    async with session_factory() as session:
        model = await session.scalar(select(DiscordParticipant))
    assert model is not None
    assert model.display_name == "Updated Student"
    assert model.username == "updated"
    assert model.avatar_hash == "new-avatar"
    assert model.is_guild_member is False
    assert model.left_at is not None
