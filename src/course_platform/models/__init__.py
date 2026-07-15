"""All ORM models; importing this module registers complete metadata."""

from course_platform.models.course import Assignment, Cohort, Course, Lesson, LessonMaterial
from course_platform.models.discord import (
    DiscordHomeworkSpace,
    DiscordInvite,
    DiscordLinkCode,
    DiscordParticipant,
    DiscordQuestion,
    DiscordStudentLink,
)
from course_platform.models.discord_delivery import (
    DiscordLessonDelivery,
    DiscordLessonDispatch,
)
from course_platform.models.progress import LessonMaterialProgress, LessonProgress
from course_platform.models.reminder import CourseReminderStep, LessonReminder
from course_platform.models.staff import StaffBotState, StaffUser
from course_platform.models.student import Enrollment, Student, StudentBotState
from course_platform.models.submission import (
    Feedback,
    FeedbackAttachment,
    Submission,
    SubmissionAttachment,
)

__all__ = [
    "Assignment",
    "Cohort",
    "Course",
    "CourseReminderStep",
    "DiscordHomeworkSpace",
    "DiscordInvite",
    "DiscordLinkCode",
    "DiscordLessonDelivery",
    "DiscordLessonDispatch",
    "DiscordParticipant",
    "DiscordQuestion",
    "DiscordStudentLink",
    "Enrollment",
    "Feedback",
    "FeedbackAttachment",
    "Lesson",
    "LessonMaterial",
    "LessonProgress",
    "LessonMaterialProgress",
    "LessonReminder",
    "StaffUser",
    "StaffBotState",
    "Student",
    "StudentBotState",
    "Submission",
    "SubmissionAttachment",
]
