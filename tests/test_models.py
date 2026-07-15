"""Smoke tests for shared metadata and the core learning workflow."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.base import Base
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Feedback,
    FeedbackAttachment,
    Lesson,
    StaffUser,
    Student,
    Submission,
    SubmissionAttachment,
)
from course_platform.models.enums import (
    AttachmentKind,
    FeedbackVerdict,
    SubmissionKind,
    SubmissionStatus,
)


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "assignments",
        "cohorts",
        "course_reminder_steps",
        "courses",
            "discord_homework_spaces",
            "discord_invites",
            "discord_lesson_deliveries",
            "discord_lesson_dispatches",
            "discord_link_codes",
            "discord_questions",
            "discord_student_links",
        "enrollments",
        "feedback",
        "feedback_attachments",
        "lessons",
        "lesson_progress",
        "lesson_materials",
        "lesson_material_progress",
        "lesson_reminders",
        "staff_users",
        "staff_bot_states",
        "students",
        "student_bot_states",
        "submission_attachments",
        "submissions",
    }


async def test_learning_workflow_can_be_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    course = Course(slug="python-course", title="Python course")
    cohort = Cohort(title="First cohort")
    lesson = Lesson(position=1, title="Introduction")
    assignment = Assignment(
        instructions="Submit the result",
        submission_kind=SubmissionKind.ANY,
    )
    lesson.assignment = assignment
    course.lessons.append(lesson)
    course.cohorts.append(cohort)

    student = Student(telegram_user_id=123456789, first_name="Student")
    enrollment = Enrollment(cohort=cohort)
    student.enrollments.append(enrollment)
    curator = StaffUser(login="curator", display_name="Course curator")

    async with session_factory() as session:
        session.add_all([course, student, curator])
        await session.flush()

        submission = Submission(
            enrollment=enrollment,
            assignment=assignment,
            text_body="Homework answer",
        )
        submission.attachments.append(
            SubmissionAttachment(
                kind=AttachmentKind.DOCUMENT,
                telegram_file_id="bot-specific-file-id",
                telegram_file_unique_id="stable-file-id",
            )
        )
        submission.feedback = Feedback(
            reviewer=curator,
            verdict=FeedbackVerdict.ACCEPTED,
            message="Accepted",
        )
        submission.feedback.attachments.append(
            FeedbackAttachment(
                kind=AttachmentKind.PHOTO,
                telegram_file_id="feedback-file-id",
                telegram_file_unique_id="feedback-stable-file-id",
            )
        )
        submission.status = SubmissionStatus.ACCEPTED
        session.add(submission)
        await session.commit()

    async with session_factory() as session:
        stored_submission = await session.scalar(select(Submission))

    assert stored_submission is not None
    assert stored_submission.status is SubmissionStatus.ACCEPTED
    assert stored_submission.attempt_number == 1
