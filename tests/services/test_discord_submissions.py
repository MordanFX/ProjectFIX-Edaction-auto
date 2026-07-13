"""Discord message confirmation submission tests."""

from datetime import UTC, datetime

from sqlalchemy import select

from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    DiscordHomeworkSpace,
    DiscordQuestion,
    Enrollment,
    Lesson,
    StaffUser,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import CourseAudience, SubmissionKind, SubmissionSource
from course_platform.services.discord_access import DiscordAccessService
from course_platform.services.discord_participants import DiscordParticipantService
from course_platform.services.discord_questions import DiscordQuestionService
from course_platform.services.discord_submissions import (
    DiscordIncomingAttachment,
    DiscordSubmissionService,
)
from course_platform.services.reviews import ReviewService


async def configured_student(session_factory) -> None:
    participant = await DiscordParticipantService(session_factory).get_or_create(
        guild_id=10,
        discord_user_id=20,
        display_name="Discord",
    )
    async with session_factory() as session:
        course = Course(
            slug="discord-submit",
            title="Discord course",
            audience=CourseAudience.DISCORD,
        )
        cohort = Cohort(title="Main")
        lesson = Lesson(
            position=1,
            title="First lesson",
            is_published=True,
            requires_view_confirmation=False,
        )
        lesson.assignment = Assignment(
            instructions="Send homework",
            submission_kind=SubmissionKind.ANY,
        )
        course.cohorts.append(cohort)
        course.lessons.append(lesson)
        session.add_all(
            [
                course,
                Enrollment(student_id=participant.student_id, cohort=cohort),
                DiscordHomeworkSpace(
                    guild_id=10,
                    discord_user_id=20,
                    student_id=participant.student_id,
                    parent_channel_id=30,
                    channel_id=40,
                    kind="private_thread",
                    display_name="Discord",
                ),
            ]
        )
        await session.commit()


async def test_confirmed_message_becomes_discord_submission(session_factory) -> None:
    await configured_student(session_factory)
    service = DiscordSubmissionService(session_factory)

    assignment = await service.current_assignment(guild_id=10, discord_user_id=20)
    assert assignment is not None
    assert assignment.course_title == "Discord course"
    assert assignment.lesson_position == 1
    assert assignment.lesson_title == "First lesson"
    assert assignment.instructions == "Send homework"

    assert await service.can_offer(guild_id=10, discord_user_id=20, channel_id=40)
    assert not await service.can_offer(guild_id=10, discord_user_id=20, channel_id=41)

    receipt = await service.submit_message(
        guild_id=10,
        discord_user_id=20,
        channel_id=40,
        message_id=50,
        text="My Discord homework",
        attachments=(
            DiscordIncomingAttachment(
                attachment_id=60,
                url="https://cdn.discord.test/homework.png",
                file_name="homework.png",
                mime_type="image/png",
                file_size=1234,
                width=800,
                height=600,
            ),
        ),
    )

    async with session_factory() as session:
        submission = await session.scalar(select(Submission))
        attachment = await session.scalar(select(SubmissionAttachment))

    assert receipt.attempt_number == 1
    assert submission is not None
    assert submission.source is SubmissionSource.DISCORD
    assert submission.source_channel_id == 40
    assert submission.source_message_id == 50
    assert submission.text_body == "My Discord homework"
    assert attachment is not None
    assert attachment.telegram_file_id is None
    assert attachment.discord_attachment_id == 60
    assert attachment.external_url == "https://cdn.discord.test/homework.png"

    queue = await ReviewService(session_factory).list_pending(
        include_reviewed=True,
        source=SubmissionSource.DISCORD,
    )
    detail = await ReviewService(session_factory).get_detail(submission.id)
    assert len(queue) == 1
    assert queue[0].source is SubmissionSource.DISCORD
    assert detail.source is SubmissionSource.DISCORD
    assert detail.attachments[0].source_available is True


async def test_discord_question_is_saved_and_resolved(session_factory) -> None:
    await configured_student(session_factory)
    service = DiscordQuestionService(session_factory)

    question = await service.create_from_message(
        guild_id=10,
        discord_user_id=20,
        channel_id=40,
        message_id=70,
        text="Need help with homework",
        attachment_count=1,
    )

    async with session_factory() as session:
        model = await session.scalar(select(DiscordQuestion))
        staff = StaffUser(login="curator", display_name="Curator")
        session.add(staff)
        await session.commit()
        staff_id = staff.id

    assert model is not None
    assert question.student_name == "Discord"
    assert question.discord_display_name == "Discord"
    assert question.text_body == "Need help with homework"
    assert question.attachment_count == 1
    assert question.status == "open"

    questions = await service.list_questions(guild_id=10, include_resolved=False)
    assert [item.question_id for item in questions] == [question.question_id]

    resolved = await service.resolve_question(
        question_id=question.question_id,
        staff_id=staff_id,
    )
    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_by == "Curator"


async def test_curator_reply_resolves_latest_open_question(session_factory) -> None:
    await configured_student(session_factory)
    service = DiscordQuestionService(session_factory)

    question = await service.create_from_message(
        guild_id=10,
        discord_user_id=20,
        channel_id=40,
        message_id=80,
        text="Can you explain this part?",
        attachment_count=0,
    )

    own_reply = await service.resolve_latest_open_in_channel(
        guild_id=10,
        channel_id=40,
        responder_discord_user_id=20,
    )
    assert own_reply is None
    open_questions = await service.list_questions(guild_id=10, include_resolved=False)
    assert open_questions[0].question_id == question.question_id

    resolved = await service.resolve_latest_open_in_channel(
        guild_id=10,
        channel_id=40,
        responder_discord_user_id=99,
    )

    assert resolved is not None
    assert resolved.question_id == question.question_id
    assert resolved.status == "resolved"
    assert await service.list_questions(guild_id=10, include_resolved=False) == []


async def test_discord_access_can_be_extended_and_closed(session_factory) -> None:
    await configured_student(session_factory)
    service = DiscordAccessService(session_factory)

    initial = await service.list_accesses(guild_id=10)
    assert len(initial) == 1
    assert initial[0].status == "no_expiry"

    extended = await service.extend_access(student_id=initial[0].student_id, months=1)
    assert extended.status in {"active", "expiring"}
    assert extended.access_source == "manual"
    assert extended.access_plan == "1_month"
    assert extended.access_expires_at is not None

    extended_again = await service.extend_access(student_id=initial[0].student_id, months=3)
    assert extended_again.access_plan == "3_month"
    assert extended_again.access_expires_at is not None
    assert extended_again.access_expires_at > extended.access_expires_at

    closed = await service.close_access(student_id=initial[0].student_id)
    assert closed.status == "revoked"


async def test_discord_access_expiry_can_be_set_manually(session_factory) -> None:
    await configured_student(session_factory)
    service = DiscordAccessService(session_factory)
    [access] = await service.list_accesses(guild_id=10)

    expires_at = datetime(2026, 9, 1, 23, 59, 59, tzinfo=UTC)
    updated = await service.set_expiry(
        student_id=access.student_id,
        expires_at=expires_at,
    )

    assert updated.access_plan == "custom"
    assert updated.access_source == "manual"
    assert updated.access_expires_at == expires_at
