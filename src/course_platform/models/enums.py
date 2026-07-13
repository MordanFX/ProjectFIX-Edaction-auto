"""Stable values persisted by the domain models."""

from enum import StrEnum


class AccessType(StrEnum):
    FREE = "free"
    PAID = "paid"
    TRIAL = "trial"
    MANUAL = "manual"


class StudentOrigin(StrEnum):
    TELEGRAM = "telegram"
    DISCORD = "discord"


class CourseAudience(StrEnum):
    TELEGRAM = "telegram"
    DISCORD = "discord"


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    REVOKED = "revoked"


class StaffRole(StrEnum):
    CURATOR = "curator"
    ADMIN = "admin"


class SubmissionStatus(StrEnum):
    SUBMITTED = "submitted"
    IN_REVIEW = "in_review"
    REVISION_REQUESTED = "revision_requested"
    ACCEPTED = "accepted"


class SubmissionSource(StrEnum):
    TELEGRAM = "telegram"
    DISCORD = "discord"


class FeedbackVerdict(StrEnum):
    REVISION_REQUESTED = "revision_requested"
    ACCEPTED = "accepted"


class UnlockRule(StrEnum):
    AFTER_VIEW = "after_view"
    AFTER_SUBMISSION = "after_submission"
    AFTER_ACCEPTANCE = "after_acceptance"


class LessonProgressStatus(StrEnum):
    LOCKED = "locked"
    AVAILABLE = "available"
    VIEWED = "viewed"
    HOMEWORK_SUBMITTED = "homework_submitted"
    COMPLETED = "completed"


class SubmissionKind(StrEnum):
    TEXT = "text"
    FILE = "file"
    PHOTO = "photo"
    VIDEO = "video"
    ANY = "any"


class AttachmentKind(StrEnum):
    DOCUMENT = "document"
    PHOTO = "photo"
    VIDEO = "video"
    VIDEO_NOTE = "video_note"


class VideoSource(StrEnum):
    PLACEHOLDER = "placeholder"
    TELEGRAM_CHANNEL = "telegram_channel"
    EXTERNAL_URL = "external_url"


class ConversationState(StrEnum):
    IDLE = "idle"
    AWAITING_HOMEWORK = "awaiting_homework"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class ReminderKind(StrEnum):
    STUDENT_GENTLE = "student_gentle"
    STUDENT_FOLLOW_UP = "student_follow_up"
    CURATOR_ALERT = "curator_alert"


class ReminderStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
