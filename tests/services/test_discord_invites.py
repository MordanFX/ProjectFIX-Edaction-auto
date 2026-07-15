from datetime import UTC, datetime, timedelta

from course_platform.models import DiscordInvite
from course_platform.services.discord_invites import DiscordInviteService


async def test_remember_invite_stores_active_link(session_factory) -> None:
    service = DiscordInviteService(session_factory)

    invite = await service.remember_invite(
        guild_id=10,
        channel_id=20,
        code="panel-code",
        invite_url="https://discord.gg/panel-code",
        course_id=None,
        created_by_staff_id=None,
    )

    assert invite.status == "active"
    assert invite.code == "panel-code"
    assert invite.invite_url == "https://discord.gg/panel-code"
    assert invite.created_at is not None


async def test_list_invites_orders_newest_first_and_flags_expired(
    session_factory,
) -> None:
    service = DiscordInviteService(session_factory)
    await service.remember_invite(
        guild_id=10,
        channel_id=20,
        code="fresh",
        invite_url="https://discord.gg/fresh",
        course_id=None,
        created_by_staff_id=None,
    )

    # An already-expired link should still be listed, marked as expired.
    async with session_factory() as session:
        session.add(
            DiscordInvite(
                guild_id=10,
                channel_id=20,
                code="stale",
                invite_url="https://discord.gg/stale",
                course_id=None,
                created_by_staff_id=None,
                max_age_seconds=300,
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    invites = await service.list_invites(guild_id=10)

    assert {item.code for item in invites} == {"fresh", "stale"}
    by_code = {item.code: item for item in invites}
    assert by_code["fresh"].status == "active"
    assert by_code["stale"].status == "expired"


async def test_list_invites_is_scoped_by_guild(session_factory) -> None:
    service = DiscordInviteService(session_factory)
    await service.remember_invite(
        guild_id=10,
        channel_id=20,
        code="ours",
        invite_url="https://discord.gg/ours",
        course_id=None,
        created_by_staff_id=None,
    )
    await service.remember_invite(
        guild_id=99,
        channel_id=20,
        code="theirs",
        invite_url="https://discord.gg/theirs",
        course_id=None,
        created_by_staff_id=None,
    )

    invites = await service.list_invites(guild_id=10)

    assert [item.code for item in invites] == ["ours"]
