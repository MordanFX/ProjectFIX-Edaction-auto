"""Telegram-to-Discord identity linking tests."""

import pytest
from sqlalchemy import select

from course_platform.models import Cohort, Course, DiscordHomeworkSpace, Enrollment
from course_platform.models.enums import EnrollmentStatus
from course_platform.services.discord_linking import (
    DiscordAccessRequiredError,
    DiscordLinkService,
    InvalidDiscordLinkCodeError,
)
from course_platform.services.students import StudentRegistration, StudentService


async def active_student(session_factory, telegram_user_id: int = 100):
    registration = await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=telegram_user_id, first_name="Alex")
    )
    async with session_factory() as session:
        course = Course(slug=f"discord-{telegram_user_id}", title="Discord course")
        cohort = Cohort(title="Main")
        course.cohorts.append(cohort)
        session.add_all([course, Enrollment(student_id=registration.student_id, cohort=cohort)])
        await session.commit()
    return registration


async def test_issues_and_redeems_one_time_code(session_factory) -> None:
    student = await active_student(session_factory)
    service = DiscordLinkService(session_factory, "test-link-secret")

    issued = await service.issue(100)
    linked = await service.redeem(
        guild_id=10,
        discord_user_id=20,
        code=issued.code.lower(),
    )

    assert len(issued.code) == 14
    assert linked.student_id == student.student_id
    assert linked.first_name == "Alex"
    assert await service.get_active_student(10, 20) == linked

    with pytest.raises(InvalidDiscordLinkCodeError):
        await service.redeem(guild_id=10, discord_user_id=20, code=issued.code)


async def test_requires_active_course_access(session_factory) -> None:
    await StudentService(session_factory).register(
        StudentRegistration(telegram_user_id=101, first_name="No access")
    )
    service = DiscordLinkService(session_factory, "test-link-secret")

    with pytest.raises(DiscordAccessRequiredError):
        await service.issue(101)


async def test_revoked_access_invalidates_existing_link(session_factory) -> None:
    await active_student(session_factory, telegram_user_id=102)
    service = DiscordLinkService(session_factory, "test-link-secret")
    issued = await service.issue(102)
    await service.redeem(guild_id=10, discord_user_id=22, code=issued.code)

    async with session_factory() as session:
        enrollment = await session.scalar(select(Enrollment))
        assert enrollment is not None
        enrollment.status = EnrollmentStatus.REVOKED
        await session.commit()

    assert await service.get_active_student(10, 22) is None


async def test_link_attaches_legacy_homework_space(session_factory) -> None:
    student = await active_student(session_factory, telegram_user_id=103)
    async with session_factory() as session:
        session.add(
            DiscordHomeworkSpace(
                guild_id=10,
                discord_user_id=23,
                parent_channel_id=30,
                channel_id=40,
                kind="private_thread",
                display_name="Legacy",
            )
        )
        await session.commit()

    service = DiscordLinkService(session_factory, "test-link-secret")
    issued = await service.issue(103)
    await service.redeem(guild_id=10, discord_user_id=23, code=issued.code)

    async with session_factory() as session:
        space = await session.scalar(select(DiscordHomeworkSpace))
        assert space is not None
        assert space.student_id == student.student_id
