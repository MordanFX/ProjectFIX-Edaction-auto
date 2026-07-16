from datetime import UTC, datetime, timedelta

import pytest

from course_platform.models import DiscordInvite
from course_platform.services.discord_invites import (
    DiscordInviteService,
    InvalidDiscordAccessCodeError,
)

SECRET = "test-invite-secret"


def build_service(session_factory) -> DiscordInviteService:
    return DiscordInviteService(session_factory, SECRET)


async def issue(service: DiscordInviteService, *, guild_id: int = 10, code: str = "panel-code"):
    return await service.remember_invite(
        guild_id=guild_id,
        channel_id=20,
        code=code,
        invite_url=f"https://discord.gg/{code}",
        course_id=None,
        created_by_staff_id=None,
    )


async def test_issued_invite_returns_plaintext_code_once(session_factory) -> None:
    service = build_service(session_factory)

    issued = await issue(service)

    assert issued.invite.status == "active"
    assert issued.access_code
    # Formatted in readable groups, and never stored in the clear.
    assert issued.access_code.count("-") == 2
    invites = await service.list_invites(guild_id=10)
    assert not hasattr(invites[0], "access_code")


async def test_access_codes_are_unique_per_seat(session_factory) -> None:
    service = build_service(session_factory)

    first = await issue(service, code="a")
    second = await issue(service, code="b")

    assert first.access_code != second.access_code


async def test_redeem_consumes_code_and_records_student(session_factory) -> None:
    service = build_service(session_factory)
    issued = await issue(service)

    redeemed = await service.redeem_access_code(
        guild_id=10, code=issued.access_code, discord_user_id=30
    )

    assert redeemed.invite_id == issued.invite.invite_id
    assert redeemed.status == "used"
    assert redeemed.used_by_discord_user_id == 30


async def test_code_cannot_be_redeemed_twice(session_factory) -> None:
    service = build_service(session_factory)
    issued = await issue(service)
    await service.redeem_access_code(
        guild_id=10, code=issued.access_code, discord_user_id=30
    )

    # A student must not be able to pass their code on to a friend.
    with pytest.raises(InvalidDiscordAccessCodeError):
        await service.redeem_access_code(
            guild_id=10, code=issued.access_code, discord_user_id=31
        )


async def test_redeem_accepts_sloppy_user_input(session_factory) -> None:
    service = build_service(session_factory)
    issued = await issue(service)

    messy = f"  {issued.access_code.lower().replace('-', ' ')}  "
    redeemed = await service.redeem_access_code(
        guild_id=10, code=messy, discord_user_id=30
    )

    assert redeemed.status == "used"


async def test_unknown_code_is_rejected(session_factory) -> None:
    service = build_service(session_factory)
    await issue(service)

    with pytest.raises(InvalidDiscordAccessCodeError):
        await service.redeem_access_code(
            guild_id=10, code="ZZZZ-ZZZZ-ZZZZ", discord_user_id=30
        )


async def test_code_from_another_guild_is_rejected(session_factory) -> None:
    service = build_service(session_factory)
    issued = await issue(service, guild_id=99)

    with pytest.raises(InvalidDiscordAccessCodeError):
        await service.redeem_access_code(
            guild_id=10, code=issued.access_code, discord_user_id=30
        )


async def test_expired_code_is_rejected(session_factory) -> None:
    service = build_service(session_factory)
    issued = await issue(service)

    async with session_factory() as session:
        model = await session.get(DiscordInvite, issued.invite.invite_id)
        model.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    with pytest.raises(InvalidDiscordAccessCodeError):
        await service.redeem_access_code(
            guild_id=10, code=issued.access_code, discord_user_id=30
        )


async def test_code_issued_under_another_secret_is_rejected(session_factory) -> None:
    issued = await issue(build_service(session_factory))
    impostor = DiscordInviteService(session_factory, "different-secret")

    with pytest.raises(InvalidDiscordAccessCodeError):
        await impostor.redeem_access_code(
            guild_id=10, code=issued.access_code, discord_user_id=30
        )


async def test_list_invites_reports_status_and_scope(session_factory) -> None:
    service = build_service(session_factory)
    fresh = await issue(service, code="fresh")
    await issue(service, guild_id=99, code="other-guild")
    used = await issue(service, code="used")
    await service.redeem_access_code(
        guild_id=10, code=used.access_code, discord_user_id=30
    )

    async with session_factory() as session:
        model = await session.get(DiscordInvite, fresh.invite.invite_id)
        model.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    invites = {item.code: item for item in await service.list_invites(guild_id=10)}

    assert set(invites) == {"fresh", "used"}
    assert invites["fresh"].status == "expired"
    assert invites["used"].status == "used"
    assert invites["used"].used_by_discord_user_id == 30
