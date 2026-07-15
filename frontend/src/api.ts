import type {
  AttachmentPlayback,
  CohortOption,
  CohortWrite,
  CourseCreate,
  CourseAnalytics,
  CourseContent,
  CourseOverview,
  CourseUpdate,
  CuratorReviewStats,
  DashboardSummary,
  DiscordAccess,
  DiscordInvite,
  DiscordLessonDispatch,
  DiscordQuestion,
  DiscordWorkspaceOverview,
  ReviewDecision,
  ReviewDetail,
  ReviewQueueItem,
  ReviewVerdict,
  ReminderStepsWrite,
  Staff,
  StaffCreate,
  StaffMember,
  StaffUpdate,
  StudentAccessUpdate,
  StudentDetail,
  StudentLessonDetail,
  StudentOverview,
  LessonCover,
  LessonWrite,
} from "./types";

const TOKEN_KEY = "course-platform-access-token";

export class APIError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (
    init.body
    && !(init.body instanceof URLSearchParams)
    && !(init.body instanceof FormData)
  ) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401) {
      sessionStorage.removeItem(TOKEN_KEY);
    }
    let message = "Не удалось выполнить запрос";
    try {
      const payload = (await response.json()) as {
        detail?: string | Array<{ msg?: string; loc?: Array<string | number> }>;
      };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        message = payload.detail
          .map((item) => item.msg || "Некорректные данные")
          .join("; ");
      }
    } catch {
      // The fallback message is intentionally used for non-JSON errors.
    }
    throw new APIError(message, response.status);
  }
  return (await response.json()) as T;
}

export async function login(loginValue: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: loginValue, password });
  const response = await request<{ access_token: string }>("/api/auth/token", {
    method: "POST",
    body: form,
  });
  sessionStorage.setItem(TOKEN_KEY, response.access_token);
}

export function hasSession(): boolean {
  return sessionStorage.getItem(TOKEN_KEY) !== null;
}

export function logout(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function getCurrentStaff(): Promise<Staff> {
  return request<Staff>("/api/auth/me");
}

export function getStaffMembers(): Promise<StaffMember[]> {
  return request<StaffMember[]>("/api/staff");
}

export function createStaffMember(payload: StaffCreate): Promise<StaffMember> {
  return request<StaffMember>("/api/staff", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateStaffMember(staffId: string, payload: StaffUpdate): Promise<StaffMember> {
  return request<StaffMember>(`/api/staff/${staffId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getReviewQueue(source?: "telegram" | "discord"): Promise<ReviewQueueItem[]> {
  const query = source ? `?source=${source}` : "";
  return request<ReviewQueueItem[]>(`/api/reviews${query}`);
}

export function getReviewDetail(submissionId: string): Promise<ReviewDetail> {
  return request<ReviewDetail>(`/api/reviews/${submissionId}`);
}

export function getCuratorReviewStats(): Promise<CuratorReviewStats> {
  return request<CuratorReviewStats>("/api/reviews/me/stats");
}

export function assignReview(submissionId: string): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/api/reviews/${submissionId}/assign`, {
    method: "POST",
  });
}

export function releaseReview(submissionId: string): Promise<ReviewQueueItem> {
  return request<ReviewQueueItem>(`/api/reviews/${submissionId}/release`, {
    method: "POST",
  });
}

export function getAttachmentPlayback(
  submissionId: string,
  attachmentId: string,
): Promise<AttachmentPlayback> {
  return request<AttachmentPlayback>(
    `/api/reviews/${submissionId}/attachments/${attachmentId}/playback`,
    { method: "POST" },
  );
}

export function getFeedbackAttachmentPlayback(
  submissionId: string,
  attachmentId: string,
): Promise<AttachmentPlayback> {
  return request<AttachmentPlayback>(
    `/api/reviews/${submissionId}/feedback-attachments/${attachmentId}/playback`,
    { method: "POST" },
  );
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/dashboard/summary");
}

export function getStudents(): Promise<StudentOverview[]> {
  return request<StudentOverview[]>("/api/students");
}

export function getStudentDetail(
  studentId: string,
  enrollmentId: string | null,
): Promise<StudentDetail> {
  const query = enrollmentId ? `?enrollment_id=${encodeURIComponent(enrollmentId)}` : "";
  return request<StudentDetail>(`/api/students/${studentId}${query}`);
}

export function getStudentLessonDetail(
  studentId: string,
  enrollmentId: string,
  lessonId: string,
): Promise<StudentLessonDetail> {
  const query = `?enrollment_id=${encodeURIComponent(enrollmentId)}`;
  return request<StudentLessonDetail>(
    `/api/students/${studentId}/lessons/${lessonId}${query}`,
  );
}

export function updateStudentAccess(
  studentId: string,
  payload: StudentAccessUpdate,
): Promise<StudentDetail> {
  return request<StudentDetail>(`/api/students/${studentId}/access`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getCourses(): Promise<CourseOverview[]> {
  return request<CourseOverview[]>("/api/courses");
}

export function getCourse(courseId: string): Promise<CourseContent> {
  return request<CourseContent>(`/api/courses/${courseId}`);
}

export function getLessonCover(lessonId: string): Promise<LessonCover> {
  return request<LessonCover>(`/api/courses/lessons/${lessonId}/cover`);
}

export function createCourse(payload: CourseCreate): Promise<CourseContent> {
  return request<CourseContent>("/api/courses", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCourseCohorts(courseId: string): Promise<CohortOption[]> {
  return request<CohortOption[]>(`/api/courses/${courseId}/cohorts`);
}

export function createCourseCohort(
  courseId: string,
  payload: CohortWrite,
): Promise<CohortOption[]> {
  return request<CohortOption[]>(`/api/courses/${courseId}/cohorts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCourseCohort(
  courseId: string,
  cohortId: string,
  payload: CohortWrite,
): Promise<CohortOption[]> {
  return request<CohortOption[]>(`/api/courses/${courseId}/cohorts/${cohortId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function updateCourse(courseId: string, payload: CourseUpdate): Promise<CourseContent> {
  return request<CourseContent>(`/api/courses/${courseId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getDiscordOverview(): Promise<DiscordWorkspaceOverview> {
  return request<DiscordWorkspaceOverview>("/api/discord/overview");
}

export function getDiscordAccesses(): Promise<DiscordAccess[]> {
  return request<DiscordAccess[]>("/api/discord/accesses");
}

export function createDiscordInvite(payload: {
  course_id?: string | null;
  max_age_seconds?: number;
} = {}): Promise<DiscordInvite> {
  return request<DiscordInvite>("/api/discord/invites", {
    method: "POST",
    body: JSON.stringify({
      course_id: payload.course_id ?? null,
      max_age_seconds: payload.max_age_seconds ?? 86400,
    }),
  });
}

export function getDiscordInvites(): Promise<DiscordInvite[]> {
  return request<DiscordInvite[]>("/api/discord/invites");
}

export function extendDiscordAccess(studentId: string, months: 1 | 3): Promise<DiscordAccess> {
  return request<DiscordAccess>(`/api/discord/accesses/${studentId}/extend`, {
    method: "POST",
    body: JSON.stringify({ months }),
  });
}

export function setDiscordAccessExpiry(studentId: string, accessExpiresAt: string): Promise<DiscordAccess> {
  return request<DiscordAccess>(`/api/discord/accesses/${studentId}/expiry`, {
    method: "POST",
    body: JSON.stringify({ access_expires_at: accessExpiresAt }),
  });
}

export function closeDiscordAccess(studentId: string): Promise<DiscordAccess> {
  return request<DiscordAccess>(`/api/discord/accesses/${studentId}/close`, {
    method: "POST",
  });
}

export function getDiscordLessonDispatches(): Promise<DiscordLessonDispatch[]> {
  return request<DiscordLessonDispatch[]>("/api/discord/lesson-dispatches");
}

export function getDiscordQuestions(): Promise<DiscordQuestion[]> {
  return request<DiscordQuestion[]>("/api/discord/questions");
}

export function resolveDiscordQuestion(questionId: string): Promise<DiscordQuestion> {
  return request<DiscordQuestion>(`/api/discord/questions/${questionId}/resolve`, {
    method: "POST",
  });
}

export function createDiscordLessonDispatch(payload: {
  lesson_id: string;
  student_ids: string[];
  custom_message: string | null;
}): Promise<DiscordLessonDispatch> {
  return request<DiscordLessonDispatch>("/api/discord/lesson-dispatches", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function assignDiscordCourse(
  studentId: string,
  courseId: string,
): Promise<DiscordWorkspaceOverview> {
  return request<DiscordWorkspaceOverview>(`/api/discord/participants/${studentId}/course`, {
    method: "PATCH",
    body: JSON.stringify({ course_id: courseId }),
  });
}

export function revokeDiscordAccess(studentId: string): Promise<DiscordWorkspaceOverview> {
  return request<DiscordWorkspaceOverview>(`/api/discord/participants/${studentId}/access`, {
    method: "DELETE",
  });
}

export function getCourseAnalytics(courseId: string): Promise<CourseAnalytics> {
  return request<CourseAnalytics>(`/api/courses/${courseId}/analytics`);
}

export function updateCourseReminderSteps(
  courseId: string,
  payload: ReminderStepsWrite,
): Promise<CourseContent> {
  return request<CourseContent>(`/api/courses/${courseId}/reminder-steps`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function createLesson(courseId: string, payload: LessonWrite): Promise<CourseContent> {
  return request<CourseContent>(`/api/courses/${courseId}/lessons`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function copyLessonFromKnowledge(
  courseId: string,
  sourceLessonId: string,
): Promise<CourseContent> {
  return request<CourseContent>(`/api/courses/${courseId}/lessons/from-knowledge`, {
    method: "POST",
    body: JSON.stringify({ source_lesson_id: sourceLessonId }),
  });
}

export function updateLesson(
  courseId: string,
  lessonId: string,
  payload: LessonWrite,
): Promise<CourseContent> {
  return request<CourseContent>(`/api/courses/${courseId}/lessons/${lessonId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function decideReview(
  submissionId: string,
  verdict: ReviewVerdict,
  message: string,
  attachment?: File | null,
): Promise<ReviewDecision> {
  if (attachment) {
    const form = new FormData();
    form.set("verdict", verdict);
    form.set("message", message);
    form.set("attachment", attachment);
    return request<ReviewDecision>(`/api/reviews/${submissionId}/decision-with-attachment`, {
      method: "POST",
      body: form,
    });
  }
  return request<ReviewDecision>(`/api/reviews/${submissionId}/decision`, {
    method: "POST",
    body: JSON.stringify({ verdict, message }),
  });
}
