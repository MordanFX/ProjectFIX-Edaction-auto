import { useEffect, useState } from "react";

import {
  APIError,
  assignStudentCurator,
  deleteTelegramStudent,
  getCourseCohorts,
  getStaffMembers,
  getStudentDetail,
  getStudentLessonDetail,
  updateStudentAccess,
} from "../api";
import type {
  CohortOption,
  CourseOverview,
  Staff,
  StaffMember,
  StudentAccessUpdate,
  StudentDetail,
  StudentLessonDetail,
  StudentOverview,
} from "../types";
import { AttachmentCard } from "./ReviewModal";
import { VimeoPreview } from "./VimeoPreview";

interface StudentModalProps {
  overview: StudentOverview;
  courses: CourseOverview[];
  staff: Staff;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

interface AccessForm {
  cohort_id: string;
  status: StudentAccessUpdate["status"];
  access_type: StudentAccessUpdate["access_type"];
  current_lesson_position: string;
}

type StudentTab = "overview" | "lessons" | "homework" | "settings";

export function StudentModal({
  overview,
  courses,
  staff,
  onClose,
  onChanged,
}: StudentModalProps) {
  const isAdmin = staff.role === "admin";
  const [detail, setDetail] = useState<StudentDetail | null>(null);
  const [curators, setCurators] = useState<StaffMember[]>([]);
  const [curatorSaving, setCuratorSaving] = useState(false);
  const [curatorError, setCuratorError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedCourseId, setSelectedCourseId] = useState(overview.course_id ?? "");
  const [cohorts, setCohorts] = useState<CohortOption[]>([]);
  const [cohortsLoading, setCohortsLoading] = useState(false);
  const [accessSaving, setAccessSaving] = useState(false);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedLessonId, setSelectedLessonId] = useState<string | null>(null);
  const [lessonDetail, setLessonDetail] = useState<StudentLessonDetail | null>(null);
  const [lessonLoading, setLessonLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<StudentTab>("overview");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [form, setForm] = useState<AccessForm>({
    cohort_id: overview.cohort_id ?? "",
    status: overview.enrollment_status ?? "active",
    access_type: overview.access_type ?? "manual",
    current_lesson_position: overview.current_lesson_position
      ? String(overview.current_lesson_position)
      : "",
  });

  useEffect(() => {
    void loadDetail();
  }, [overview.student_id, overview.enrollment_id]);

  useEffect(() => {
    if (!isAdmin) return;
    getStaffMembers()
      .then(setCurators)
      .catch(() => setCurators([]));
  }, [isAdmin]);

  useEffect(() => {
    const courseId = detail?.course_id ?? selectedCourseId;
    if (!courseId) {
      setCohorts([]);
      return;
    }
    let active = true;
    setCohortsLoading(true);
    getCourseCohorts(courseId)
      .then((items) => active && setCohorts(items))
      .catch(() => active && setAccessError("Не удалось загрузить группы курса"))
      .finally(() => active && setCohortsLoading(false));
    return () => {
      active = false;
    };
  }, [detail?.course_id, selectedCourseId]);

  async function loadDetail() {
    setError(null);
    try {
      const loaded = await getStudentDetail(
        overview.student_id,
        overview.enrollment_id,
      );
      setDetail(loaded);
      setSelectedCourseId(loaded.course_id ?? "");
      setForm({
        cohort_id: loaded.cohort_id ?? "",
        status: loaded.enrollment_status ?? "active",
        access_type: loaded.access_type ?? "manual",
        current_lesson_position: loaded.current_lesson_position
          ? String(loaded.current_lesson_position)
          : "",
      });
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось загрузить ученика",
      );
    }
  }

  async function saveAccess() {
    if (!form.cohort_id) {
      setAccessError("Выбери группу курса");
      return;
    }
    setAccessSaving(true);
    setAccessError(null);
    try {
      const updated = await updateStudentAccess(overview.student_id, {
        cohort_id: form.cohort_id,
        status: form.status,
        access_type: form.access_type,
        current_lesson_position: form.current_lesson_position
          ? Number(form.current_lesson_position)
          : null,
      });
      setDetail(updated);
      setSelectedCourseId(updated.course_id ?? selectedCourseId);
      await onChanged();
    } catch (caughtError) {
      setAccessError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось сохранить доступ",
      );
    } finally {
      setAccessSaving(false);
    }
  }

  async function openLesson(lessonId: string) {
    if (!detail?.enrollment_id) return;
    if (selectedLessonId === lessonId) {
      setSelectedLessonId(null);
      setLessonDetail(null);
      return;
    }
    setSelectedLessonId(lessonId);
    setLessonDetail(null);
    setLessonLoading(true);
    try {
      setLessonDetail(
        await getStudentLessonDetail(
          detail.student_id,
          detail.enrollment_id,
          lessonId,
        ),
      );
    } catch {
      setAccessError("Не удалось загрузить детали урока");
    } finally {
      setLessonLoading(false);
    }
  }

  async function deleteStudent() {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await deleteTelegramStudent(overview.student_id);
      await onChanged();
      onClose();
    } catch (caughtError) {
      setDeleteError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось удалить ученика",
      );
    } finally {
      setDeleteBusy(false);
    }
  }

  async function assignCurator(curatorId: string | null) {
    setCuratorSaving(true);
    setCuratorError(null);
    try {
      const updated = await assignStudentCurator(overview.student_id, curatorId);
      setDetail(updated);
      await onChanged();
    } catch (caughtError) {
      setCuratorError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось закрепить куратора",
      );
    } finally {
      setCuratorSaving(false);
    }
  }

  const student = detail ?? overview;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="student-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Ученик ${overview.name}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}>
          ×
        </button>
        {!detail ? (
          <div className="student-detail-loading">
            <div className="spinner" />
            <span>{error || "Загружаем данные ученика…"}</span>
          </div>
        ) : (
          <div className="student-detail">
            <header className="student-detail__hero">
              <span className="student-detail__avatar">{initials(student.name)}</span>
              <div>
                <span className="student-detail__eyebrow">Карточка ученика</span>
                <h2>{student.name}</h2>
                <p>{student.username ? `@${student.username}` : "без username"}</p>
              </div>
              <span className={`curator-pin ${detail.assigned_curator_id ? "curator-pin--assigned" : ""}`}>
                {detail.assigned_curator_id ? `Куратор: ${detail.assigned_curator_name}` : "Не закреплён"}
              </span>
              <EnrollmentStatus status={detail.enrollment_status} />
            </header>

            <nav className="student-detail__tabs" aria-label="Разделы карточки ученика">
              <button type="button" className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")}>Обзор</button>
              <button type="button" className={activeTab === "lessons" ? "active" : ""} onClick={() => setActiveTab("lessons")}>Уроки</button>
              <button type="button" className={activeTab === "homework" ? "active" : ""} onClick={() => setActiveTab("homework")}>Домашки</button>
              <button type="button" className={activeTab === "settings" ? "active" : ""} onClick={() => setActiveTab("settings")}>Настройки</button>
            </nav>

            {activeTab === "overview" && (
              <div className="student-detail__tab-panel">
                <section className="student-detail__stats">
                  <Stat label="Прогресс" value={`${detail.progress_percent}%`} />
                  <Stat label="Принято ДЗ" value={`${detail.accepted_submissions}/${detail.total_assignments}`} />
                  <Stat label="Попыток" value={detail.total_attempts} />
                  <Stat label="Ожидают" value={detail.pending_submissions} />
                </section>

                {detail.course_id ? (
                  <section className="student-detail__course">
                    <div className="student-detail__section-heading">
                      <div>
                        <span>Текущий курс</span>
                        <h3>{detail.course_title}</h3>
                      </div>
                      <strong>{detail.progress_percent}%</strong>
                    </div>
                    <div className="student-detail__course-meta">
                      <span>{detail.cohort_title ?? "Без группы"}</span>
                      <span>{accessLabel(detail.access_type)}</span>
                      <span>{enrollmentLabel(detail.enrollment_status)}</span>
                    </div>
                    <div className="progress-track progress-track--detail">
                      <span style={{ width: `${detail.progress_percent}%` }} />
                    </div>
                    <div className="student-detail__course-footer">
                      <span>Текущий урок: {detail.current_lesson_position ?? "—"}</span>
                      <span>ДЗ: {detail.accepted_submissions} из {detail.total_assignments}</span>
                    </div>
                  </section>
                ) : (
                  <section className="student-detail__course student-detail__course--empty">
                    <div className="student-detail__section-heading">
                      <div>
                        <span>Курс не назначен</span>
                        <h3>Ученик пока не подключён к обучению</h3>
                      </div>
                    </div>
                    <button type="button" onClick={() => setActiveTab("settings")}>Назначить курс</button>
                  </section>
                )}

                <section
                  className={`student-reminders ${detail.requires_attention ? "student-reminders--attention" : ""}`}
                >
                  <span className="student-reminders__icon">🔔</span>
                  <div>
                    <span>Напоминания</span>
                    <strong>
                      {detail.reminders_enabled ? "Включены" : "Отключены"}
                    </strong>
                    <p>
                      Тихие часы: {hour(detail.quiet_hours_start)}–{hour(detail.quiet_hours_end)}
                    </p>
                  </div>
                  <div className="student-reminders__settings">
                    <span>{detail.next_reminder_at ? formatDate(detail.next_reminder_at) : "Нет активных"}</span>
                  </div>
                </section>
              </div>
            )}

            {activeTab === "lessons" && (
              <section className="student-detail__section student-detail__tab-panel">
                <div className="student-detail__section-heading">
                  <div>
                    <span>Учебный путь</span>
                    <h3>Прогресс по урокам</h3>
                  </div>
                  <small>{detail.lesson_progress.length} уроков</small>
                </div>
                <div className="lesson-timeline">
                  {detail.lesson_progress.map((lesson) => (
                    <button
                      type="button"
                      key={lesson.lesson_id}
                      className={`lesson-timeline__item lesson-timeline__item--${lesson.status} ${selectedLessonId === lesson.lesson_id ? "active" : ""}`}
                      onClick={() => void openLesson(lesson.lesson_id)}
                    >
                      <span className="lesson-timeline__number">{lesson.position}</span>
                      <div>
                        <strong>{lesson.title}</strong>
                        <span>{lessonActivity(lesson)}</span>
                      </div>
                      <span className="lesson-timeline__status">
                        {lessonStatus(lesson.status)}
                      </span>
                    </button>
                  ))}
                </div>
                {selectedLessonId && (
                  <LessonPanel detail={lessonDetail} loading={lessonLoading} />
                )}
              </section>
            )}

            {activeTab === "homework" && (
              <section className="student-detail__section student-detail__tab-panel">
                <div className="student-detail__section-heading">
                  <div>
                    <span>История</span>
                    <h3>Последние сдачи</h3>
                  </div>
                  <small>{detail.recent_submissions.length} записей</small>
                </div>
                <div className="submission-history">
                  {detail.recent_submissions.length ? (
                    detail.recent_submissions.map((submission) => (
                      <article className="submission-history__item" key={submission.submission_id}>
                        <div className="submission-history__lesson">
                          <span>Урок {submission.lesson_position}</span>
                          <strong>{submission.lesson_title}</strong>
                        </div>
                        <div className="submission-history__meta">
                          <span>{formatDate(submission.submitted_at)}</span>
                          <span>Попытка {submission.attempt_number}</span>
                          <span>Вложений: {submission.attachment_count}</span>
                        </div>
                        <span className={`submission-history__status submission-history__status--${submission.status}`}>
                          {submissionStatus(submission.status)}
                        </span>
                        {submission.attachments.length > 0 && (
                          <div className="attachment-list attachment-list--history">
                            {submission.attachments.map((attachment) => (
                              <AttachmentCard
                                key={attachment.id}
                                submissionId={submission.submission_id}
                                attachment={attachment}
                                source="telegram"
                              />
                            ))}
                          </div>
                        )}
                        {submission.feedback_message && <p>{submission.feedback_message}</p>}
                      </article>
                    ))
                  ) : (
                    <p className="student-detail__empty">Ученик ещё не сдавал задания.</p>
                  )}
                </div>
              </section>
            )}

            {activeTab === "settings" && (
              <div className="student-detail__tab-panel">
                <section className="student-detail__facts">
                  <Fact label="Telegram ID" value={String(detail.telegram_user_id)} />
                  <Fact label="Регистрация" value={formatDate(detail.registered_at)} />
                  <Fact label="Последняя активность" value={formatDate(detail.last_activity_at)} />
                  <Fact label="Часовой пояс" value={detail.timezone} />
                </section>
                {isAdmin && (
                  <CuratorSection
                    detail={detail}
                    curators={curators}
                    saving={curatorSaving}
                    error={curatorError}
                    onAssign={(curatorId) => void assignCurator(curatorId)}
                  />
                )}
                <AccessSection
                  detail={detail}
                  courses={courses}
                  selectedCourseId={selectedCourseId}
                  cohorts={cohorts}
                  form={form}
                  loading={cohortsLoading}
                  saving={accessSaving}
                  error={accessError}
                  deleteError={deleteError}
                  deleteBusy={deleteBusy}
                  onCourseChange={(courseId) => {
                    setSelectedCourseId(courseId);
                    setForm({ ...form, cohort_id: "" });
                  }}
                  onFormChange={setForm}
                  onSave={() => void saveAccess()}
                  onDelete={() => void deleteStudent()}
                />
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function CuratorSection({
  detail,
  curators,
  saving,
  error,
  onAssign,
}: {
  detail: StudentDetail;
  curators: StaffMember[];
  saving: boolean;
  error: string | null;
  onAssign: (curatorId: string | null) => void;
}) {
  return (
    <section className="student-detail__section">
      <div className="student-detail__section-heading">
        <div>
          <span>Доступ куратора</span>
          <h3>Закрепление ученика</h3>
        </div>
      </div>
      <p className="muted">
        Если ученик закреплён за куратором, остальные кураторы не видят его вопросы,
        ДЗ и карточку — только вы и закреплённый куратор.
      </p>
      <div className="student-access-form">
        <label>
          <span>Куратор</span>
          <select
            value={detail.assigned_curator_id ?? ""}
            disabled={saving}
            onChange={(event) => onAssign(event.target.value || null)}
          >
            <option value="">Не закреплён (общая очередь)</option>
            {curators.map((member) => (
              <option key={member.id} value={member.id}>
                {member.display_name} · {member.role === "admin" ? "admin" : "куратор"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <div className="form-error">{error}</div>}
    </section>
  );
}

function AccessSection({
  detail,
  courses,
  selectedCourseId,
  cohorts,
  form,
  loading,
  saving,
  error,
  deleteError,
  deleteBusy,
  onCourseChange,
  onFormChange,
  onSave,
  onDelete,
}: {
  detail: StudentDetail;
  courses: CourseOverview[];
  selectedCourseId: string;
  cohorts: CohortOption[];
  form: AccessForm;
  loading: boolean;
  saving: boolean;
  error: string | null;
  deleteError: string | null;
  deleteBusy: boolean;
  onCourseChange: (courseId: string) => void;
  onFormChange: (form: AccessForm) => void;
  onSave: () => void;
  onDelete: () => void;
}) {
  return (
    <section className="student-detail__section student-detail__section--access">
      <div className="student-detail__section-heading">
        <div>
          <span>Доступ</span>
          <h3>{detail.course_id ? "Группа и статус ученика" : "Назначить курс"}</h3>
        </div>
        <small>{detail.course_id ? "Доступ можно изменить" : "Курс не назначен"}</small>
      </div>
      <div className="student-access-form">
        {!detail.course_id && (
          <label>
            <span>Курс</span>
            <select value={selectedCourseId} onChange={(event) => onCourseChange(event.target.value)}>
              <option value="">Выбери курс</option>
              {courses.map((course) => (
                <option key={course.course_id} value={course.course_id}>{course.title}</option>
              ))}
            </select>
          </label>
        )}
        <label>
          <span>Группа курса</span>
          <select
            value={form.cohort_id}
            disabled={!selectedCourseId || loading}
            onChange={(event) => onFormChange({ ...form, cohort_id: event.target.value })}
          >
            <option value="">Выбери группу</option>
            {cohorts.map((cohort) => (
              <option key={cohort.cohort_id} value={cohort.cohort_id}>
                {cohort.title}{cohort.is_active ? "" : " · архив"} · {cohort.students_count}
              </option>
            ))}
          </select>
        </label>
        {detail.course_id && (
          <>
            <label>
              <span>Статус</span>
              <select value={form.status} onChange={(event) => onFormChange({ ...form, status: event.target.value as AccessForm["status"] })}>
                <option value="active">Активен</option>
                <option value="paused">Пауза</option>
                <option value="completed">Завершён</option>
                <option value="revoked">Закрыт</option>
              </select>
            </label>
            <label>
              <span>Тип доступа</span>
              <select value={form.access_type} onChange={(event) => onFormChange({ ...form, access_type: event.target.value as AccessForm["access_type"] })}>
                <option value="manual">Ручной</option>
                <option value="trial">Пробный</option>
                <option value="free">Бесплатный</option>
                <option value="paid">Платный</option>
              </select>
            </label>
            <label>
              <span>Текущий урок</span>
              <input type="number" min={1} value={form.current_lesson_position} onChange={(event) => onFormChange({ ...form, current_lesson_position: event.target.value })} />
            </label>
          </>
        )}
      </div>
      {error && <div className="form-error">{error}</div>}
      {deleteError && <div className="form-error">{deleteError}</div>}
      <div className="student-access-actions">
        <span>{loading ? "Загружаем группы…" : detail.cohort_title ?? "Выбери курс и группу"}</span>
        <div className="student-access-actions__buttons">
          <button
            type="button"
            className="student-delete-button"
            disabled={deleteBusy}
            onClick={onDelete}
          >
            {deleteBusy ? "Удаляем…" : "Удалить ученика"}
          </button>
          <button className="secondary-button" disabled={saving || loading || !form.cohort_id} onClick={onSave}>
            {saving ? "Сохраняем…" : detail.course_id ? "Сохранить доступ" : "Назначить курс"}
          </button>
        </div>
      </div>
    </section>
  );
}

function LessonPanel({ detail, loading }: { detail: StudentLessonDetail | null; loading: boolean }) {
  if (loading || !detail) {
    return <div className="student-lesson-detail student-lesson-detail--loading"><div className="spinner" /><span>Загружаем урок…</span></div>;
  }
  return (
    <article className="student-lesson-detail">
      <header className="student-lesson-detail__header">
        <div><span>Урок {detail.position}</span><h4>{detail.title}</h4></div>
        <span className="lesson-timeline__status lesson-timeline__status--large">{lessonStatus(detail.status)}</span>
      </header>
      <div className="student-lesson-detail__content">
        <section><span>Материал урока</span><p>{detail.description || "Описание не заполнено."}</p>{detail.video_source === "external_url" && detail.video_reference && <><VimeoPreview url={detail.video_reference} title={`Видео урока ${detail.title}`} /><a href={detail.video_reference} target="_blank" rel="noreferrer">Открыть видео ↗</a></>}</section>
        <section><span>Домашнее задание</span><p>{detail.assignment_instructions || "Домашнее задание не предусмотрено."}</p><small>{detail.submission_kind ? `Формат: ${detail.submission_kind}` : ""}</small></section>
      </div>
      <div className="student-lesson-detail__attempts">
        <div><span>Попытки ученика</span><strong>{detail.attempts.length}</strong></div>
        {detail.attempts.map((attempt) => (
          <article key={attempt.submission_id}>
            <header><strong>Попытка {attempt.attempt_number}</strong><span className={`submission-history__status submission-history__status--${attempt.status}`}>{submissionStatus(attempt.status)}</span></header>
            <small>{formatDate(attempt.submitted_at)} · вложений: {attempt.attachment_count}</small>
            {attempt.text_body && <p>{attempt.text_body}</p>}
            {attempt.feedback_message && <blockquote>{attempt.feedback_message}</blockquote>}
          </article>
        ))}
      </div>
    </article>
  );
}

function Fact({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function Stat({ label, value }: { label: string; value: string | number }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
function EnrollmentStatus({ status }: { status: StudentDetail["enrollment_status"] }) { return <span className={`status-badge status-badge--${status ?? "none"}`}>{enrollmentLabel(status)}</span>; }
function enrollmentLabel(status: StudentDetail["enrollment_status"]): string { return status ? { active: "Учится", paused: "Пауза", completed: "Завершён", revoked: "Доступ закрыт" }[status] : "Без курса"; }
function accessLabel(type: StudentDetail["access_type"]): string { return type ? { manual: "Ручной доступ", trial: "Пробный", free: "Бесплатный", paid: "Платный" }[type] : "Доступ не задан"; }
function lessonStatus(status: StudentDetail["lesson_progress"][number]["status"]): string { return { locked: "Закрыт", available: "Доступен", viewed: "Просмотрен", homework_submitted: "ДЗ отправлено", completed: "Завершён" }[status]; }
function submissionStatus(status: StudentDetail["recent_submissions"][number]["status"]): string { return { submitted: "Отправлено", in_review: "На проверке", revision_requested: "Доработка", accepted: "Принято" }[status]; }
function lessonActivity(lesson: StudentDetail["lesson_progress"][number]): string { return lesson.completed_at ? `Завершён ${formatDate(lesson.completed_at)}` : lesson.homework_submitted_at ? `ДЗ отправлено ${formatDate(lesson.homework_submitted_at)}` : lesson.viewed_at ? `Просмотрен ${formatDate(lesson.viewed_at)}` : lesson.available_at ? `Доступен с ${formatDate(lesson.available_at)}` : "Ожидает открытия"; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function hour(value: number): string { return `${String(value).padStart(2, "0")}:00`; }
function initials(name: string): string { return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join(""); }
