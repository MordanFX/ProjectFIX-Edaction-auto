export type StaffRole = "curator" | "admin";
export type ReviewVerdict = "accepted" | "revision_requested";
export type SubmissionStatus =
  | "submitted"
  | "in_review"
  | "revision_requested"
  | "accepted";

export interface Staff {
  id: string;
  login: string;
  display_name: string;
  role: StaffRole;
}

export interface ReviewQueueItem {
  submission_id: string;
  student_id: string;
  student_name: string;
  student_username: string | null;
  course_title: string;
  lesson_position: number;
  lesson_title: string;
  attempt_number: number;
  submitted_at: string;
  text_body: string | null;
  attachment_count: number;
  attachment_kind: AttachmentKind | null;
  attachment_file_name: string | null;
  attachment_mime_type: string | null;
  status: SubmissionStatus;
  source: "telegram" | "discord";
  source_guild_id: string | null;
  source_channel_id: string | null;
  source_message_id: string | null;
}

export type AttachmentKind = "document" | "photo" | "video" | "video_note";

export interface ReviewAttachment {
  id: string;
  kind: AttachmentKind;
  file_name: string | null;
  mime_type: string | null;
  file_size: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  source_available: boolean;
}

export interface ReviewDetail extends ReviewQueueItem {
  reviewed_at: string | null;
  feedback_verdict: ReviewVerdict | null;
  feedback_message: string | null;
  reviewer_name: string | null;
  attachments: ReviewAttachment[];
  previous_attempts: ReviewAttempt[];
}

export interface ReviewAttempt {
  submission_id: string;
  attempt_number: number;
  submitted_at: string;
  text_body: string | null;
  status: SubmissionStatus;
  source: "telegram" | "discord";
  reviewed_at: string | null;
  feedback_verdict: ReviewVerdict | null;
  feedback_message: string | null;
  reviewer_name: string | null;
  attachments: ReviewAttachment[];
}

export interface AttachmentPlayback {
  url: string;
  expires_in: number;
}

export interface DashboardSummary {
  pending_reviews: number;
  active_students: number;
  completed_enrollments: number;
  active_courses: number;
  average_progress_percent: number;
}

export type DiscordMemberStatus = "active" | "completed" | "no_access" | "left" | "unregistered";

export interface DiscordMemberOverview {
  guild_id: string;
  discord_user_id: string;
  discord_display_name: string | null;
  discord_username: string | null;
  discord_global_name: string | null;
  avatar_url: string | null;
  student_id: string | null;
  student_name: string | null;
  enrollment_id: string | null;
  course_id: string | null;
  cohort_id: string | null;
  course_title: string | null;
  cohort_title: string | null;
  enrollment_status: "active" | "paused" | "completed" | "revoked" | null;
  access_type: "free" | "paid" | "trial" | "manual" | null;
  current_lesson_position: number | null;
  total_lessons: number;
  channel_id: string | null;
  thread_name: string | null;
  space_kind: string | null;
  status: DiscordMemberStatus;
  is_guild_member: boolean;
  registered_at: string | null;
  guild_joined_at: string | null;
  last_activity_at: string | null;
  left_at: string | null;
  space_created_at: string | null;
  total_submissions: number;
  pending_submissions: number;
  last_submission_at: string | null;
}

export interface DiscordWorkspaceOverview {
  participants: number;
  active_students: number;
  private_spaces: number;
  unregistered_spaces: number;
  submissions_enabled: boolean;
  members: DiscordMemberOverview[];
}

export interface DiscordLessonDispatch {
  dispatch_id: string;
  course_id: string;
  course_title: string;
  lesson_id: string;
  lesson_position: number;
  lesson_title: string;
  custom_message: string | null;
  created_by: string;
  created_at: string;
  recipient_count: number;
  pending_count: number;
  sent_count: number;
  failed_count: number;
}

export interface DiscordQuestion {
  question_id: string;
  guild_id: string;
  channel_id: string;
  message_id: string;
  discord_user_id: string;
  student_id: string | null;
  student_name: string | null;
  discord_display_name: string | null;
  discord_username: string | null;
  text_body: string | null;
  attachment_count: number;
  status: "open" | "resolved";
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

export type DiscordAccessStatus =
  | "active"
  | "expiring"
  | "expired"
  | "revoked"
  | "no_course"
  | "no_expiry";

export interface DiscordAccess {
  student_id: string;
  guild_id: string;
  discord_user_id: string;
  discord_display_name: string;
  discord_username: string | null;
  avatar_url: string | null;
  course_id: string | null;
  course_title: string | null;
  enrollment_status: "active" | "paused" | "completed" | "revoked" | null;
  access_started_at: string | null;
  access_expires_at: string | null;
  access_source: string | null;
  access_plan: string | null;
  status: DiscordAccessStatus;
  days_left: number | null;
  channel_id: string | null;
  thread_name: string | null;
  last_activity_at: string | null;
}

export interface StudentOverview {
  student_id: string;
  enrollment_id: string | null;
  course_id: string | null;
  cohort_id: string | null;
  name: string;
  username: string | null;
  is_active: boolean;
  course_title: string | null;
  cohort_title: string | null;
  enrollment_status: "active" | "paused" | "completed" | "revoked" | null;
  access_type: "free" | "paid" | "trial" | "manual" | null;
  current_lesson_position: number | null;
  total_lessons: number;
  accepted_submissions: number;
  total_assignments: number;
  progress_percent: number;
}

export type LessonProgressStatus =
  | "locked"
  | "available"
  | "viewed"
  | "homework_submitted"
  | "completed";

export interface StudentLessonProgress {
  lesson_id: string;
  position: number;
  title: string;
  status: LessonProgressStatus;
  release_at: string | null;
  available_at: string | null;
  viewed_at: string | null;
  homework_submitted_at: string | null;
  completed_at: string | null;
}

export interface StudentSubmissionHistory {
  submission_id: string;
  lesson_position: number;
  lesson_title: string;
  attempt_number: number;
  status: SubmissionStatus;
  submitted_at: string;
  reviewed_at: string | null;
  attachment_count: number;
  feedback_verdict: ReviewVerdict | null;
  feedback_message: string | null;
}

export interface StudentDetail extends StudentOverview {
  telegram_user_id: number;
  language_code: string | null;
  registered_at: string;
  enrolled_at: string | null;
  access_type: "free" | "paid" | "trial" | "manual" | null;
  total_attempts: number;
  pending_submissions: number;
  revision_requests: number;
  last_activity_at: string;
  timezone: string;
  quiet_hours_start: number;
  quiet_hours_end: number;
  reminders_enabled: boolean;
  next_reminder_at: string | null;
  next_reminder_kind: "student_gentle" | "student_follow_up" | "curator_alert" | null;
  requires_attention: boolean;
  lesson_progress: StudentLessonProgress[];
  recent_submissions: StudentSubmissionHistory[];
}

export interface StudentLessonAttempt {
  submission_id: string;
  attempt_number: number;
  status: SubmissionStatus;
  submitted_at: string;
  reviewed_at: string | null;
  text_body: string | null;
  attachment_count: number;
  feedback_verdict: ReviewVerdict | null;
  feedback_message: string | null;
}

export interface StudentLessonDetail {
  student_id: string;
  enrollment_id: string;
  lesson_id: string;
  position: number;
  title: string;
  description: string | null;
  video_source: "placeholder" | "telegram_channel" | "external_url";
  video_reference: string | null;
  release_offset_hours: number;
  requires_view_confirmation: boolean;
  is_published: boolean;
  status: LessonProgressStatus;
  release_at: string | null;
  available_at: string | null;
  viewed_at: string | null;
  homework_submitted_at: string | null;
  completed_at: string | null;
  assignment_instructions: string | null;
  submission_kind: "text" | "file" | "photo" | "video" | "any" | null;
  assignment_is_required: boolean | null;
  attempts: StudentLessonAttempt[];
}

export interface CourseOverview {
  course_id: string;
  slug: string;
  title: string;
  description: string | null;
  audience: "telegram" | "discord";
  unlock_rule: "after_view" | "after_submission" | "after_acceptance";
  is_active: boolean;
  lessons_count: number;
  cohorts_count: number;
  students_count: number;
}

export interface CohortOption {
  cohort_id: string;
  title: string;
  is_active: boolean;
  students_count: number;
}

export interface CohortWrite {
  title: string;
  is_active: boolean;
}

export interface LessonStageAnalytics {
  position: number;
  title: string;
  students_count: number;
}

export interface CohortAnalytics {
  cohort_id: string;
  title: string;
  students_count: number;
  active_students: number;
  completed_students: number;
  average_progress_percent: number;
  lesson_stages: LessonStageAnalytics[];
}

export interface CourseAnalytics {
  course_id: string;
  total_students: number;
  average_progress_percent: number;
  cohorts: CohortAnalytics[];
}

export type VideoSource = "placeholder" | "telegram_channel" | "external_url";
export type SubmissionKind = "text" | "file" | "photo" | "video" | "any";

export interface AssignmentContent {
  instructions: string;
  submission_kind: SubmissionKind;
  is_required: boolean;
}

export interface LessonContent {
  lesson_id: string;
  position: number;
  title: string;
  description: string | null;
  video_source: VideoSource;
  video_reference: string | null;
  materials: LessonMaterial[];
  release_offset_hours: number;
  requires_view_confirmation: boolean;
  is_published: boolean;
  assignment: AssignmentContent | null;
}

export interface LessonMaterial {
  material_id: string;
  position: number;
  title: string;
  description: string | null;
  kind: "video" | "image";
  video_source: VideoSource;
  video_reference: string | null;
}

export interface LessonCover {
  cover_url: string | null;
  source: "image" | "vimeo" | null;
}

export interface CourseContent {
  course_id: string;
  slug: string;
  title: string;
  description: string | null;
  audience: "telegram" | "discord";
  unlock_rule: CourseOverview["unlock_rule"];
  is_active: boolean;
  lessons: LessonContent[];
  reminder_steps: ReminderStep[];
}

export type ReminderKind = "student_gentle" | "student_follow_up" | "curator_alert";

export interface ReminderStep {
  sequence: number;
  delay_hours: number;
  kind: ReminderKind;
  message_text: string;
  is_active: boolean;
}

export interface ReminderStepsWrite {
  steps: Omit<ReminderStep, "sequence">[];
}

export interface StudentAccessUpdate {
  cohort_id: string;
  status: "active" | "paused" | "completed" | "revoked";
  access_type: "free" | "paid" | "trial" | "manual";
  current_lesson_position: number | null;
}

export interface CourseUpdate {
  title: string;
  description: string | null;
  is_active: boolean;
}

export interface CourseCreate {
  title: string;
  description: string | null;
  audience: "telegram" | "discord";
  is_active: boolean;
}

export interface LessonWrite {
  title: string;
  description: string | null;
  video_source: VideoSource;
  video_reference: string | null;
  release_offset_hours: number;
  requires_view_confirmation: boolean;
  is_published: boolean;
  assignment: AssignmentContent | null;
}

export interface ReviewDecision {
  submission_id: string;
  verdict: ReviewVerdict;
  current_lesson_position: number;
  course_completed: boolean;
}
