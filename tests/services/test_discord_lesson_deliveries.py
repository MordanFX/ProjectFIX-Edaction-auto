"""Curator-triggered Discord lesson delivery tests."""

from sqlalchemy import select

from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordLessonDelivery,
    Enrollment,
    Lesson,
    StaffUser,
)
from course_platform.models.enums import (
    CourseAudience,
    NotificationStatus,
    VideoSource,
)
from course_platform.services.discord_lesson_deliveries import (
    DiscordLessonDeliveryService,
    DiscordLessonDispatchError,
)
from course_platform.services.discord_participants import DiscordParticipantService


async def configured_dispatch(session_factory):
    participant = await DiscordParticipantService(session_factory).get_or_create(
        guild_id=10,
        discord_user_id=20,
        display_name="Discord Student",
    )
    async with session_factory() as session:
        staff = StaffUser(login="curator", display_name="Curator")
        course = Course(
            slug="discord-delivery",
            title="Discord course",
            audience=CourseAudience.DISCORD,
        )
        cohort = Cohort(title="Main")
        lesson = Lesson(
            position=1,
            title="First lesson",
            description="Lesson material",
            is_published=True,
            video_source=VideoSource.EXTERNAL_URL,
            video_reference="https://example.test/video",
        )
        lesson.assignment = Assignment(instructions="Build the homework")
        course.cohorts.append(cohort)
        course.lessons.append(lesson)
        session.add_all(
            [
                staff,
                course,
                Enrollment(student_id=participant.student_id, cohort=cohort),
                DiscordHomeworkSpace(
                    guild_id=10,
                    discord_user_id=20,
                    student_id=participant.student_id,
                    parent_channel_id=30,
                    channel_id=40,
                    channel_name="dz-discord-student-0020",
                    kind="private_thread",
                    display_name="Discord Student",
                ),
            ]
        )
        await session.commit()
        return participant, staff.id, lesson.id


async def test_creates_sends_and_tracks_lesson_dispatch(session_factory) -> None:
    participant, staff_id, lesson_id = await configured_dispatch(session_factory)
    service = DiscordLessonDeliveryService(session_factory)

    dispatch = await service.create_dispatch(
        guild_id=10,
        lesson_id=lesson_id,
        student_ids=(participant.student_id,),
        custom_message="Submit by Friday",
        staff_id=staff_id,
    )
    pending = await service.list_pending()

    assert dispatch.recipient_count == 1
    assert dispatch.pending_count == 1
    assert len(pending) == 1
    assert pending[0].channel_id == 40
    assert "<@20>" in pending[0].content
    assert "Build the homework" in pending[0].content
    assert "https://example.test/video" in pending[0].content
    assert "Submit by Friday" in pending[0].content
    assert "Как сдать" in pending[0].content
    assert "Отправить на проверку" in pending[0].content

    await service.mark_sent(pending[0].delivery_id, discord_message_id=50)
    history = await service.list_dispatches()
    assert history[0].sent_count == 1
    assert history[0].pending_count == 0

    async with session_factory() as session:
        delivery = await session.scalar(select(DiscordLessonDelivery))
    assert delivery is not None
    assert delivery.status is NotificationStatus.SENT
    assert delivery.discord_message_id == 50
    assert delivery.attempts == 1


async def test_prevents_duplicate_lesson_delivery(session_factory) -> None:
    participant, staff_id, lesson_id = await configured_dispatch(session_factory)
    service = DiscordLessonDeliveryService(session_factory)
    payload = {
        "guild_id": 10,
        "lesson_id": lesson_id,
        "student_ids": (participant.student_id,),
        "custom_message": None,
        "staff_id": staff_id,
    }
    await service.create_dispatch(**payload)

    try:
        await service.create_dispatch(**payload)
    except DiscordLessonDispatchError as error:
        assert str(error) == "lesson-already-dispatched"
    else:
        raise AssertionError("duplicate dispatch was accepted")
