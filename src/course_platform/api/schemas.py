"""Pydantic response models for the curator API."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from course_platform.models.enums import (
    AccessType,
    AttachmentKind,
    CourseAudience,
    EnrollmentStatus,
    FeedbackVerdict,
    LessonProgressStatus,
    ReminderKind,
    StaffRole,
    SubmissionKind,
    SubmissionSource,
    SubmissionStatus,
    UnlockRule,
    VideoSource,
)
from course_platform.services.admin_dashboard import (
    CourseOverview,
    DashboardSummary,
    StudentDetail,
    StudentLessonDetail,
    StudentOverview,
)
from course_platform.services.course_admin import CourseAnalytics, CourseContent, LessonContent
from course_platform.services.discord_access import DiscordAccessOverview, DiscordAccessStatus
from course_platform.services.discord_dashboard import (
    DiscordMemberOverview,
    DiscordMemberStatus,
    DiscordWorkspaceOverview,
)
from course_platform.services.discord_invites import (
    DiscordInviteOverview,
    IssuedDiscordInvite,
)
from course_platform.services.discord_lesson_deliveries import (
    DiscordLessonDispatchOverview,
)
from course_platform.services.discord_questions import DiscordQuestionOverview
from course_platform.services.reviews import ReviewDetail, ReviewQueueItem
from course_platform.services.telegram_questions import TelegramQuestionOverview


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"


class StaffResponse(APIModel):
    id: UUID
    login: str
    display_name: str
    role: StaffRole


class StaffMemberResponse(StaffResponse):
    telegram_user_id: int | None
    is_active: bool
    created_at: datetime
    pending_assigned: int = 0
    reviewed_total: int = 0
    accepted_total: int = 0
    revision_total: int = 0


class StaffCreateRequest(APIModel):
    login: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    role: StaffRole = StaffRole.CURATOR
    telegram_user_id: int | None = None
    is_active: bool = True


class StaffUpdateRequest(APIModel):
    password: str | None = Field(default=None, min_length=8, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    role: StaffRole
    telegram_user_id: int | None = None
    is_active: bool


class ReviewQueueItemResponse(APIModel):
    submission_id: UUID
    student_id: UUID
    student_name: str
    student_username: str | None
    course_title: str
    lesson_position: int
    lesson_title: str
    attempt_number: int
    submitted_at: datetime
    text_body: str | None
    attachment_count: int
    attachment_kind: AttachmentKind | None
    attachment_file_name: str | None
    attachment_mime_type: str | None
    status: SubmissionStatus
    source: SubmissionSource
    source_guild_id: str | None
    source_channel_id: str | None
    source_message_id: str | None
    assigned_reviewer_id: UUID | None
    assigned_reviewer_name: str | None
    assigned_at: datetime | None

    @classmethod
    def from_domain(cls, item: ReviewQueueItem) -> "ReviewQueueItemResponse":
        payload = asdict(item)
        for field in ("source_guild_id", "source_channel_id", "source_message_id"):
            value = payload[field]
            payload[field] = str(value) if value is not None else None
        return cls(**payload)


class ReviewAttachmentResponse(APIModel):
    id: UUID
    kind: AttachmentKind
    file_name: str | None
    mime_type: str | None
    file_size: int | None
    duration_seconds: int | None
    width: int | None
    height: int | None
    source_available: bool


class ReviewAttemptResponse(APIModel):
    submission_id: UUID
    attempt_number: int
    submitted_at: datetime
    text_body: str | None
    status: SubmissionStatus
    source: SubmissionSource
    reviewed_at: datetime | None
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None
    reviewer_name: str | None
    attachments: list[ReviewAttachmentResponse]
    feedback_attachments: list[ReviewAttachmentResponse]


class ReviewDetailResponse(ReviewQueueItemResponse):
    reviewed_at: datetime | None
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None
    reviewer_name: str | None
    attachments: list[ReviewAttachmentResponse]
    feedback_attachments: list[ReviewAttachmentResponse]
    previous_attempts: list[ReviewAttemptResponse]

    @classmethod
    def from_domain(cls, item: ReviewDetail) -> "ReviewDetailResponse":
        payload = asdict(item)
        payload["attachments"] = list(payload["attachments"])
        payload["feedback_attachments"] = list(payload["feedback_attachments"])
        payload["previous_attempts"] = list(payload["previous_attempts"])
        for field in ("source_guild_id", "source_channel_id", "source_message_id"):
            value = payload[field]
            payload[field] = str(value) if value is not None else None
        return cls(**payload)


class CuratorReviewStatsResponse(APIModel):
    pending_assigned: int
    reviewed_total: int
    accepted_total: int
    revision_total: int
    telegram_reviewed: int
    discord_reviewed: int


class AttachmentPlaybackResponse(APIModel):
    url: str
    expires_in: int


class DashboardSummaryResponse(APIModel):
    pending_reviews: int
    active_students: int
    completed_enrollments: int
    active_courses: int
    average_progress_percent: int

    @classmethod
    def from_domain(cls, item: DashboardSummary) -> "DashboardSummaryResponse":
        return cls(**asdict(item))


class DiscordMemberOverviewResponse(APIModel):
    guild_id: str
    discord_user_id: str
    discord_display_name: str | None
    discord_username: str | None
    discord_global_name: str | None
    avatar_url: str | None
    student_id: UUID | None
    student_name: str | None
    enrollment_id: UUID | None
    course_id: UUID | None
    cohort_id: UUID | None
    course_title: str | None
    cohort_title: str | None
    enrollment_status: EnrollmentStatus | None
    access_type: AccessType | None
    current_lesson_position: int | None
    total_lessons: int
    channel_id: str | None
    thread_name: str | None
    space_kind: str | None
    status: DiscordMemberStatus
    is_guild_member: bool
    registered_at: datetime | None
    guild_joined_at: datetime | None
    last_activity_at: datetime | None
    left_at: datetime | None
    space_created_at: datetime | None
    total_submissions: int
    pending_submissions: int
    last_submission_at: datetime | None

    @classmethod
    def from_domain(cls, item: DiscordMemberOverview) -> "DiscordMemberOverviewResponse":
        payload = asdict(item)
        payload["guild_id"] = str(item.guild_id)
        payload["discord_user_id"] = str(item.discord_user_id)
        payload["channel_id"] = str(item.channel_id) if item.channel_id is not None else None
        return cls(**payload)


class DiscordWorkspaceOverviewResponse(APIModel):
    participants: int
    active_students: int
    private_spaces: int
    unregistered_spaces: int
    submissions_enabled: bool
    members: list[DiscordMemberOverviewResponse]

    @classmethod
    def from_domain(cls, item: DiscordWorkspaceOverview) -> "DiscordWorkspaceOverviewResponse":
        return cls(
            participants=item.participants,
            active_students=item.active_students,
            private_spaces=item.private_spaces,
            unregistered_spaces=item.unregistered_spaces,
            submissions_enabled=item.submissions_enabled,
            members=[DiscordMemberOverviewResponse.from_domain(member) for member in item.members],
        )


class DiscordInviteCreateRequest(APIModel):
    course_id: UUID | None = None
    max_age_seconds: int = Field(default=86400, ge=300, le=604800)


class DiscordInviteResponse(APIModel):
    invite_id: UUID
    guild_id: str
    channel_id: str
    code: str
    invite_url: str
    course_id: UUID | None
    max_age_seconds: int
    expires_at: datetime
    created_at: datetime
    used_at: datetime | None
    used_by_discord_user_id: str | None
    status: str

    @classmethod
    def from_domain(cls, item: DiscordInviteOverview) -> "DiscordInviteResponse":
        return cls(
            invite_id=item.invite_id,
            guild_id=str(item.guild_id),
            channel_id=str(item.channel_id),
            code=item.code,
            invite_url=item.invite_url,
            course_id=item.course_id,
            max_age_seconds=item.max_age_seconds,
            expires_at=item.expires_at,
            created_at=item.created_at,
            used_at=item.used_at,
            used_by_discord_user_id=(
                str(item.used_by_discord_user_id)
                if item.used_by_discord_user_id is not None
                else None
            ),
            status=item.status,
        )


class DiscordInviteCreatedResponse(DiscordInviteResponse):
    """Creation response. ``access_code`` is plaintext and returned only here —
    only its digest is stored, so it cannot be shown again later."""

    access_code: str

    @classmethod
    def from_issued(cls, issued: IssuedDiscordInvite) -> "DiscordInviteCreatedResponse":
        base = DiscordInviteResponse.from_domain(issued.invite)
        return cls(**base.model_dump(), access_code=issued.access_code)


class DiscordLessonDispatchCreateRequest(APIModel):
    lesson_id: UUID
    student_ids: list[UUID] = Field(min_length=1, max_length=1000)
    custom_message: str | None = Field(default=None, max_length=1000)


class DiscordLessonDispatchResponse(APIModel):
    dispatch_id: UUID
    course_id: UUID
    course_title: str
    lesson_id: UUID
    lesson_position: int
    lesson_title: str
    custom_message: str | None
    created_by: str
    created_at: datetime
    recipient_count: int
    pending_count: int
    sent_count: int
    failed_count: int

    @classmethod
    def from_domain(cls, item: DiscordLessonDispatchOverview) -> "DiscordLessonDispatchResponse":
        return cls(**asdict(item))


class DiscordQuestionResponse(APIModel):
    question_id: UUID
    guild_id: str
    channel_id: str
    message_id: str
    discord_user_id: str
    student_id: UUID | None
    student_name: str | None
    discord_display_name: str | None
    discord_username: str | None
    text_body: str | None
    attachment_count: int
    status: str
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None

    @classmethod
    def from_domain(cls, item: DiscordQuestionOverview) -> "DiscordQuestionResponse":
        payload = asdict(item)
        payload["guild_id"] = str(item.guild_id)
        payload["channel_id"] = str(item.channel_id)
        payload["message_id"] = str(item.message_id)
        payload["discord_user_id"] = str(item.discord_user_id)
        return cls(**payload)


class TelegramQuestionResponse(APIModel):
    question_id: UUID
    student_id: UUID
    student_name: str
    student_username: str | None
    lesson_position: int | None
    lesson_title: str | None
    course_title: str | None
    text_body: str | None
    has_attachment: bool
    attachment_kind: AttachmentKind | None
    status: str
    answer_text: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None

    @classmethod
    def from_domain(cls, item: TelegramQuestionOverview) -> "TelegramQuestionResponse":
        return cls(**asdict(item))


class DiscordAccessResponse(APIModel):
    student_id: UUID
    guild_id: str
    discord_user_id: str
    discord_display_name: str
    discord_username: str | None
    avatar_url: str | None
    course_id: UUID | None
    course_title: str | None
    enrollment_status: EnrollmentStatus | None
    access_started_at: datetime | None
    access_expires_at: datetime | None
    access_source: str | None
    access_plan: str | None
    status: DiscordAccessStatus
    days_left: int | None
    channel_id: str | None
    thread_name: str | None
    last_activity_at: datetime | None

    @classmethod
    def from_domain(cls, item: DiscordAccessOverview) -> "DiscordAccessResponse":
        payload = asdict(item)
        payload["guild_id"] = str(item.guild_id)
        payload["discord_user_id"] = str(item.discord_user_id)
        payload["channel_id"] = str(item.channel_id) if item.channel_id is not None else None
        return cls(**payload)


class DiscordAccessExtendRequest(APIModel):
    months: int = Field(ge=1, le=36)


class DiscordAccessSetExpiryRequest(APIModel):
    access_expires_at: datetime


class StudentOverviewResponse(APIModel):
    student_id: UUID
    enrollment_id: UUID | None
    course_id: UUID | None
    cohort_id: UUID | None
    name: str
    username: str | None
    is_active: bool
    course_title: str | None
    cohort_title: str | None
    enrollment_status: EnrollmentStatus | None
    access_type: AccessType | None
    current_lesson_position: int | None
    total_lessons: int
    accepted_submissions: int
    total_assignments: int
    progress_percent: int

    @classmethod
    def from_domain(cls, item: StudentOverview) -> "StudentOverviewResponse":
        return cls(**asdict(item))


class StudentLessonProgressResponse(APIModel):
    lesson_id: UUID
    position: int
    title: str
    status: LessonProgressStatus
    release_at: datetime | None
    available_at: datetime | None
    viewed_at: datetime | None
    homework_submitted_at: datetime | None
    completed_at: datetime | None


class StudentSubmissionHistoryResponse(APIModel):
    submission_id: UUID
    lesson_position: int
    lesson_title: str
    attempt_number: int
    status: SubmissionStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    attachment_count: int
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None
    attachments: list[ReviewAttachmentResponse] = []


class StudentDetailResponse(StudentOverviewResponse):
    telegram_user_id: int
    language_code: str | None
    registered_at: datetime
    enrolled_at: datetime | None
    access_type: AccessType | None
    total_attempts: int
    pending_submissions: int
    revision_requests: int
    last_activity_at: datetime
    timezone: str
    quiet_hours_start: int
    quiet_hours_end: int
    reminders_enabled: bool
    next_reminder_at: datetime | None
    next_reminder_kind: ReminderKind | None
    requires_attention: bool
    lesson_progress: list[StudentLessonProgressResponse]
    recent_submissions: list[StudentSubmissionHistoryResponse]

    @classmethod
    def from_domain(cls, item: StudentDetail) -> "StudentDetailResponse":
        return cls(**asdict(item))


class StudentLessonAttemptResponse(APIModel):
    submission_id: UUID
    attempt_number: int
    status: SubmissionStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    text_body: str | None
    attachment_count: int
    feedback_verdict: FeedbackVerdict | None
    feedback_message: str | None


class StudentLessonDetailResponse(APIModel):
    student_id: UUID
    enrollment_id: UUID
    lesson_id: UUID
    position: int
    title: str
    description: str | None
    video_source: VideoSource
    video_reference: str | None
    release_offset_hours: int
    requires_view_confirmation: bool
    is_published: bool
    status: LessonProgressStatus
    release_at: datetime | None
    available_at: datetime | None
    viewed_at: datetime | None
    homework_submitted_at: datetime | None
    completed_at: datetime | None
    assignment_instructions: str | None
    submission_kind: SubmissionKind | None
    assignment_is_required: bool | None
    attempts: list[StudentLessonAttemptResponse]

    @classmethod
    def from_domain(cls, item: StudentLessonDetail) -> "StudentLessonDetailResponse":
        payload = asdict(item)
        payload["attempts"] = list(payload["attempts"])
        return cls(**payload)


class CourseOverviewResponse(APIModel):
    course_id: UUID
    slug: str
    title: str
    description: str | None
    audience: CourseAudience
    unlock_rule: UnlockRule
    is_active: bool
    lessons_count: int
    cohorts_count: int
    students_count: int

    @classmethod
    def from_domain(cls, item: CourseOverview) -> "CourseOverviewResponse":
        return cls(**asdict(item))


class CohortResponse(APIModel):
    cohort_id: UUID
    title: str
    is_active: bool
    students_count: int


class LessonStageAnalyticsResponse(APIModel):
    position: int
    title: str
    students_count: int


class CohortAnalyticsResponse(APIModel):
    cohort_id: UUID
    title: str
    students_count: int
    active_students: int
    completed_students: int
    average_progress_percent: int
    lesson_stages: list[LessonStageAnalyticsResponse]


class CourseAnalyticsResponse(APIModel):
    course_id: UUID
    total_students: int
    average_progress_percent: int
    cohorts: list[CohortAnalyticsResponse]

    @classmethod
    def from_domain(cls, item: CourseAnalytics) -> "CourseAnalyticsResponse":
        return cls(**asdict(item))


class CohortWriteRequest(APIModel):
    title: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class AssignmentContentResponse(APIModel):
    instructions: str
    submission_kind: SubmissionKind
    is_required: bool


class LessonMaterialResponse(APIModel):
    material_id: UUID
    position: int
    title: str
    description: str | None
    kind: str
    video_source: VideoSource
    video_reference: str | None


class LessonContentResponse(APIModel):
    lesson_id: UUID
    position: int
    title: str
    description: str | None
    video_source: VideoSource
    video_reference: str | None
    materials: list[LessonMaterialResponse]
    release_offset_hours: int
    requires_view_confirmation: bool
    is_published: bool
    assignment: AssignmentContentResponse | None

    @classmethod
    def from_domain(cls, item: LessonContent) -> "LessonContentResponse":
        return cls(**asdict(item))


class LessonCoverResponse(APIModel):
    cover_url: str | None
    source: str | None


class ReminderStepResponse(APIModel):
    sequence: int
    delay_hours: int
    kind: ReminderKind
    message_text: str
    is_active: bool


class ReminderStepWriteRequest(APIModel):
    delay_hours: int = Field(ge=0, le=8760)
    kind: ReminderKind
    message_text: str = Field(min_length=1, max_length=4000)
    is_active: bool = True


class ReminderStepsWriteRequest(APIModel):
    steps: list[ReminderStepWriteRequest] = Field(max_length=10)


class CourseContentResponse(APIModel):
    course_id: UUID
    slug: str
    title: str
    description: str | None
    audience: CourseAudience
    unlock_rule: UnlockRule
    is_active: bool
    lessons: list[LessonContentResponse]
    reminder_steps: list[ReminderStepResponse]

    @classmethod
    def from_domain(cls, item: CourseContent) -> "CourseContentResponse":
        payload = asdict(item)
        payload["lessons"] = list(payload["lessons"])
        payload["reminder_steps"] = list(payload["reminder_steps"])
        return cls(**payload)


class StudentAccessUpdateRequest(APIModel):
    cohort_id: UUID
    status: EnrollmentStatus = EnrollmentStatus.ACTIVE
    access_type: AccessType = AccessType.MANUAL
    current_lesson_position: int | None = Field(default=None, ge=1)


class DiscordCourseAssignmentRequest(APIModel):
    course_id: UUID


class StudentAccessUpdateResponse(StudentDetailResponse):
    pass


class CourseUpdateRequest(APIModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    is_active: bool


class CourseCreateRequest(APIModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    audience: CourseAudience = CourseAudience.TELEGRAM
    is_active: bool = True


class AssignmentContentRequest(APIModel):
    instructions: str = Field(min_length=1, max_length=12000)
    submission_kind: SubmissionKind = SubmissionKind.ANY
    is_required: bool = True


class LessonWriteRequest(APIModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=12000)
    video_source: VideoSource = VideoSource.PLACEHOLDER
    video_reference: str | None = Field(default=None, max_length=4000)
    release_offset_hours: int = Field(default=0, ge=0, le=8760)
    requires_view_confirmation: bool = True
    is_published: bool = False
    assignment: AssignmentContentRequest | None = None


class LessonCopyRequest(APIModel):
    source_lesson_id: UUID


class ReviewDecisionRequest(APIModel):
    verdict: FeedbackVerdict
    message: str = Field(min_length=1, max_length=4000)


class ReviewDecisionResponse(APIModel):
    submission_id: UUID
    verdict: FeedbackVerdict
    current_lesson_position: int
    course_completed: bool
