import { FormEvent, useEffect, useState } from "react";

import {
  APIError,
  copyLessonFromKnowledge,
  createCourseCohort,
  createLesson,
  getCourse,
  getCourseAnalytics,
  getCourseCohorts,
  updateCourse,
  updateCourseCohort,
  updateCourseReminderSteps,
  updateLesson,
} from "../api";
import type {
  CohortOption,
  CohortWrite,
  CourseContent,
  CourseAnalytics,
  CourseOverview,
  LessonContent,
  LessonWrite,
  ReminderStep,
} from "../types";
import { getVimeoEmbedUrl } from "../video";
import { LessonImportModal } from "./LessonImportModal";
import { VimeoPreview } from "./VimeoPreview";

interface CourseModalProps {
  overview: CourseOverview;
  knowledgeCourses: CourseOverview[];
  onClose: () => void;
  onChanged: () => Promise<void>;
  onDispatchLesson: (courseId: string, lessonId: string) => void;
}

interface CourseForm {
  title: string;
  description: string;
  is_active: boolean;
}

export function CourseModal({
  overview,
  knowledgeCourses,
  onClose,
  onChanged,
  onDispatchLesson,
}: CourseModalProps) {
  const [course, setCourse] = useState<CourseContent | null>(null);
  const [analytics, setAnalytics] = useState<CourseAnalytics | null>(null);
  const [cohorts, setCohorts] = useState<CohortOption[]>([]);
  const [courseForm, setCourseForm] = useState<CourseForm>({
    title: overview.title,
    description: overview.description ?? "",
    is_active: overview.is_active,
  });
  const [selectedCohortId, setSelectedCohortId] = useState<string | null>(null);
  const [cohortForm, setCohortForm] = useState<CohortWrite>({
    title: "",
    is_active: true,
  });
  const [selectedLessonId, setSelectedLessonId] = useState<string | null>(null);
  const [lessonForm, setLessonForm] = useState<LessonWrite>(emptyLesson());
  const [reminderSteps, setReminderSteps] = useState<ReminderStep[]>([]);
  const [creatingLesson, setCreatingLesson] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getCourse(overview.course_id)
      .then((loadedCourse) => {
        if (!active) return;
        setCourse(loadedCourse);
        setReminderSteps(loadedCourse.reminder_steps);
        setCourseForm({
          title: loadedCourse.title,
          description: loadedCourse.description ?? "",
          is_active: loadedCourse.is_active,
        });
        if (loadedCourse.lessons[0]) {
          selectLesson(loadedCourse.lessons[0]);
        }
      })
      .catch((caughtError) => {
        if (active) setError(errorMessage(caughtError, "Не удалось загрузить курс"));
      });
    Promise.all([
      getCourseCohorts(overview.course_id),
      getCourseAnalytics(overview.course_id),
    ])
      .then(([loadedCohorts, loadedAnalytics]) => {
        if (!active) return;
        setCohorts(loadedCohorts);
        setAnalytics(loadedAnalytics);
        if (loadedCohorts[0]) selectCohort(loadedCohorts[0]);
      })
      .catch(() => {
        if (active) setNotice("Курс открыт. Аналитика загружается отдельно.");
      });
    return () => {
      active = false;
    };
  }, [overview.course_id]);

  function selectLesson(lesson: LessonContent) {
    setSelectedLessonId(lesson.lesson_id);
    setLessonForm(lessonToForm(lesson));
    setCreatingLesson(false);
    setError(null);
    setNotice(null);
  }

  function startLesson() {
    setSelectedLessonId(null);
    setLessonForm(emptyLesson());
    setCreatingLesson(true);
    setError(null);
    setNotice(null);
  }

  function selectCohort(cohort: CohortOption) {
    setSelectedCohortId(cohort.cohort_id);
    setCohortForm({ title: cohort.title, is_active: cohort.is_active });
  }

  async function saveCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!courseForm.title.trim()) return setError("Укажи название курса");
    setBusy(true);
    setError(null);
    try {
      const updated = await updateCourse(overview.course_id, {
        title: courseForm.title.trim(),
        description: courseForm.description.trim() || null,
        is_active: courseForm.is_active,
      });
      setCourse(updated);
      setNotice("Курс сохранён");
      await onChanged();
    } catch (caughtError) {
      setError(errorMessage(caughtError, "Не удалось сохранить курс"));
    } finally {
      setBusy(false);
    }
  }

  async function saveCohort(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!cohortForm.title.trim()) return setError("Укажи название группы");
    setBusy(true);
    setError(null);
    try {
      const payload = { ...cohortForm, title: cohortForm.title.trim() };
      const updated = selectedCohortId
        ? await updateCourseCohort(overview.course_id, selectedCohortId, payload)
        : await createCourseCohort(overview.course_id, payload);
      setCohorts(updated);
      const selected = selectedCohortId
        ? updated.find((item) => item.cohort_id === selectedCohortId)
        : updated.find((item) => item.title === payload.title);
      if (selected) selectCohort(selected);
      setNotice("Группа сохранена");
      setAnalytics(await getCourseAnalytics(overview.course_id));
      await onChanged();
    } catch (caughtError) {
      setError(errorMessage(caughtError, "Не удалось сохранить группу"));
    } finally {
      setBusy(false);
    }
  }

  async function saveLesson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!lessonForm.title.trim()) return setError("Укажи название урока");
    setBusy(true);
    setError(null);
    try {
      const payload = normalizeLesson(lessonForm);
      const updated = selectedLessonId
        ? await updateLesson(overview.course_id, selectedLessonId, payload)
        : await createLesson(overview.course_id, payload);
      setCourse(updated);
      const selected = selectedLessonId
        ? updated.lessons.find((item) => item.lesson_id === selectedLessonId)
        : updated.lessons.at(-1);
      if (selected) selectLesson(selected);
      setNotice(creatingLesson ? "Урок создан" : "Урок сохранён");
      await onChanged();
    } catch (caughtError) {
      setError(errorMessage(caughtError, "Не удалось сохранить урок"));
    } finally {
      setBusy(false);
    }
  }

  async function importLesson(sourceLessonId: string) {
    setBusy(true);
    setError(null);
    try {
      const updated = await copyLessonFromKnowledge(overview.course_id, sourceLessonId);
      setCourse(updated);
      const imported = updated.lessons.at(-1);
      if (imported) selectLesson(imported);
      setNotice("Урок добавлен из базы знаний");
      await onChanged();
    } catch (caughtError) {
      setError(errorMessage(caughtError, "Не удалось добавить урок из базы знаний"));
      throw caughtError;
    } finally {
      setBusy(false);
    }
  }

  async function saveReminderSteps(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reminderSteps.some((step) => !step.message_text.trim())) {
      return setError("Укажи текст для каждой ступени напоминаний");
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await updateCourseReminderSteps(overview.course_id, {
        steps: reminderSteps.map(({ delay_hours, kind, message_text, is_active }) => ({
          delay_hours,
          kind,
          message_text: message_text.trim(),
          is_active,
        })),
      });
      setCourse(updated);
      setReminderSteps(updated.reminder_steps);
      setNotice("Сценарий напоминаний сохранён");
    } catch (caughtError) {
      setError(errorMessage(caughtError, "Не удалось сохранить напоминания"));
    } finally {
      setBusy(false);
    }
  }

  function updateReminderStep(index: number, patch: Partial<ReminderStep>) {
    setReminderSteps((current) =>
      current.map((step, stepIndex) =>
        stepIndex === index ? { ...step, ...patch } : step,
      ),
    );
  }

  function addReminderStep() {
    setReminderSteps((current) => [
      ...current,
      {
        sequence: current.length + 1,
        delay_hours: current.at(-1)?.delay_hours ?? 24,
        kind: "student_gentle",
        message_text: "Урок «{lesson_title}» ждёт тебя. Вернись, когда будет удобно.",
        is_active: true,
      },
    ]);
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="course-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Курс ${overview.title}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}>×</button>
        {!course ? (
          <div className="course-builder-loading">
            <div className="spinner" />
            <span>{error || "Загружаем конструктор курса…"}</span>
          </div>
        ) : (
          <div className="course-builder">
            <header className="course-builder__hero">
              <span>{course.audience === "telegram" ? "Telegram-курс" : "Discord-курс"} · {course.slug}</span>
              <h2>{course.title}</h2>
              <p>{unlockLabel(course.unlock_rule)} · {course.lessons.length} уроков</p>
            </header>
            {error && <div className="course-builder__error">{error}</div>}
            {notice && <div className="course-builder__notice">✓ {notice}</div>}

            <form className="course-settings-form" onSubmit={saveCourse}>
              <SectionTitle eyebrow="Основное" title="Карточка курса">
                <label className="switch-field">
                  <input type="checkbox" checked={courseForm.is_active} onChange={(event) => setCourseForm({ ...courseForm, is_active: event.target.checked })} />
                  <span>Курс активен</span>
                </label>
              </SectionTitle>
              <div className="course-form-grid">
                <label><span>Название</span><input value={courseForm.title} maxLength={255} onChange={(event) => setCourseForm({ ...courseForm, title: event.target.value })} /></label>
                <label className="course-form-grid__wide"><span>Описание</span><textarea rows={4} value={courseForm.description} onChange={(event) => setCourseForm({ ...courseForm, description: event.target.value })} /></label>
              </div>
              <FormActions hint="Название и описание видны куратору и ученикам"><button className="course-save-button" disabled={busy}>Сохранить курс</button></FormActions>
            </form>

            <form className="course-reminders-panel" onSubmit={saveReminderSteps}>
              <SectionTitle eyebrow="Автоматизация" title="Напоминания по урокам">
                <button
                  type="button"
                  disabled={reminderSteps.length >= 10}
                  onClick={addReminderStep}
                >
                  + Ступень
                </button>
              </SectionTitle>
              <p className="course-reminders-panel__lead">
                Задержка считается от момента, когда урок стал доступен. Тихие часы
                ученика применяются автоматически.
              </p>
              {reminderSteps.length ? (
                <div className="reminder-step-list">
                  {reminderSteps.map((step, index) => (
                    <article className="reminder-step" key={`${step.sequence}-${index}`}>
                      <div className="reminder-step__number">{index + 1}</div>
                      <label>
                        <span>Через сколько часов</span>
                        <input
                          type="number"
                          min={0}
                          max={8760}
                          value={step.delay_hours}
                          onChange={(event) => updateReminderStep(index, { delay_hours: Number(event.target.value) })}
                        />
                      </label>
                      <label>
                        <span>Получатель</span>
                        <select value={step.kind} onChange={(event) => updateReminderStep(index, { kind: event.target.value as ReminderStep["kind"] })}>
                          <option value="student_gentle">Ученик · мягко</option>
                          <option value="student_follow_up">Ученик · повторно</option>
                          <option value="curator_alert">Куратор</option>
                        </select>
                      </label>
                      <label className="reminder-step__message">
                        <span>Текст сообщения</span>
                        <textarea
                          rows={3}
                          maxLength={4000}
                          value={step.message_text}
                          onChange={(event) => updateReminderStep(index, { message_text: event.target.value })}
                        />
                      </label>
                      <button
                        className="reminder-step__remove"
                        type="button"
                        onClick={() => setReminderSteps((current) => current.filter((_, stepIndex) => stepIndex !== index))}
                      >
                        Удалить
                      </button>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="student-detail__empty">
                  Напоминания отключены. Добавь первую ступень, чтобы запустить сценарий.
                </div>
              )}
              <FormActions hint="Доступные переменные: {lesson_title}, {course_title}, {student_name}">
                <button className="course-save-button" disabled={busy}>Сохранить напоминания</button>
              </FormActions>
            </form>

            <section className="course-analytics-panel">
              <SectionTitle eyebrow="Аналитика" title="Движение по потокам">
                <div className="course-analytics-panel__summary">
                  <strong>{analytics?.total_students ?? 0}</strong>
                  <span>учеников · средний прогресс {analytics?.average_progress_percent ?? 0}%</span>
                </div>
              </SectionTitle>
              {analytics?.cohorts.length ? (
                <div className="cohort-analytics-list">
                  {analytics.cohorts.map((cohort) => (
                    <article className="cohort-analytics" key={cohort.cohort_id}>
                      <header>
                        <div>
                          <strong>{cohort.title}</strong>
                          <span>{cohort.active_students} активных · {cohort.completed_students} завершили</span>
                        </div>
                        <b>{cohort.average_progress_percent}%</b>
                      </header>
                      <div className="cohort-analytics__progress">
                        <i style={{ width: `${cohort.average_progress_percent}%` }} />
                      </div>
                      <div className="lesson-stage-grid">
                        {cohort.lesson_stages.map((stage) => (
                          <div className={stage.students_count ? "has-students" : ""} key={stage.position} title={stage.title}>
                            <span>Урок {stage.position}</span>
                            <strong>{stage.students_count}</strong>
                            <small>{stage.title}</small>
                          </div>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="student-detail__empty">В потоках пока нет данных для аналитики.</div>
              )}
            </section>

            <section className="course-cohorts-panel">
              <SectionTitle eyebrow="Группы" title="Потоки курса">
                <button type="button" onClick={() => { setSelectedCohortId(null); setCohortForm({ title: "", is_active: true }); }}>+ Новая группа</button>
              </SectionTitle>
              <div className="course-cohort-layout">
                <aside className="lesson-sidebar">
                  <div className="lesson-sidebar__list">
                    {cohorts.length ? cohorts.map((cohort) => (
                      <button type="button" className={selectedCohortId === cohort.cohort_id ? "active" : ""} key={cohort.cohort_id} onClick={() => selectCohort(cohort)}>
                        <span>{cohort.students_count}</span><div><strong>{cohort.title}</strong><small>{cohort.is_active ? "Активная" : "Архив"} · {cohort.students_count} учеников</small></div>
                      </button>
                    )) : <div className="student-detail__empty">Групп пока нет.</div>}
                  </div>
                </aside>
                <form className="lesson-editor" onSubmit={saveCohort}>
                  <SectionTitle eyebrow={selectedCohortId ? "Редактирование" : "Новая группа"} title="Параметры группы">
                    <label className="switch-field"><input type="checkbox" checked={cohortForm.is_active} onChange={(event) => setCohortForm({ ...cohortForm, is_active: event.target.checked })} /><span>Группа активна</span></label>
                  </SectionTitle>
                  <div className="course-form-grid"><label className="course-form-grid__wide"><span>Название группы</span><input required maxLength={255} value={cohortForm.title} onChange={(event) => setCohortForm({ ...cohortForm, title: event.target.value })} /></label></div>
                  <FormActions hint="Группы используются при назначении доступа"><button className="course-save-button" disabled={busy}>{selectedCohortId ? "Сохранить группу" : "Создать группу"}</button></FormActions>
                </form>
              </div>
            </section>

            <section className="lesson-workspace">
              <aside className="lesson-sidebar">
                <SectionTitle eyebrow="Программа" title="Уроки"><button type="button" onClick={startLesson}>+</button></SectionTitle>
                <div className="lesson-sidebar__list">
                  {course.lessons.map((lesson) => (
                    <button type="button" className={selectedLessonId === lesson.lesson_id ? "active" : ""} key={lesson.lesson_id} onClick={() => selectLesson(lesson)}>
                      <span>{lesson.position}</span><div><strong>{lesson.title}</strong><small>{lesson.is_published ? "Опубликован" : "Черновик"}</small></div>
                    </button>
                  ))}
                </div>
                <button type="button" className="new-lesson-button" onClick={startLesson}>+ Новый урок</button>
                <button type="button" className="new-lesson-button secondary" onClick={() => setImportOpen(true)}>Выбрать из базы знаний</button>
              </aside>
              <LessonEditor
                form={lessonForm}
                materials={course.lessons.find((lesson) => lesson.lesson_id === selectedLessonId)?.materials ?? []}
                setForm={setLessonForm}
                creating={creatingLesson}
                busy={busy}
                onSubmit={saveLesson}
                onDispatch={course.audience === "discord" && selectedLessonId && lessonForm.is_published ? () => onDispatchLesson(course.course_id, selectedLessonId) : null}
              />
            </section>
            {importOpen && (
              <LessonImportModal
                courses={knowledgeCourses}
                targetCourseId={course.course_id}
                onClose={() => setImportOpen(false)}
                onImport={importLesson}
              />
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function LessonEditor({ form, materials, setForm, creating, busy, onSubmit, onDispatch }: { form: LessonWrite; materials: LessonContent["materials"]; setForm: (form: LessonWrite) => void; creating: boolean; busy: boolean; onSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>; onDispatch: (() => void) | null }) {
  return (
    <form className="lesson-editor" onSubmit={onSubmit}>
      <SectionTitle eyebrow={creating ? "Новый урок" : "Редактирование"} title={creating ? "Добавить урок" : "Содержание урока"}>
        <label className="switch-field"><input type="checkbox" checked={form.is_published} onChange={(event) => setForm({ ...form, is_published: event.target.checked })} /><span>Опубликован</span></label>
      </SectionTitle>
      <div className="course-form-grid">
        <label className="course-form-grid__wide"><span>Название</span><input required maxLength={255} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
        <label className="course-form-grid__wide"><span>Описание</span><textarea rows={4} value={form.description ?? ""} onChange={(event) => setForm({ ...form, description: event.target.value || null })} /></label>
        <label><span>Источник видео</span><select value={form.video_source} onChange={(event) => setForm({ ...form, video_source: event.target.value as LessonWrite["video_source"] })}><option value="placeholder">Пока без видео</option><option value="telegram_channel">Telegram-канал</option><option value="external_url">Внешняя ссылка</option></select></label>
        <label><span>{form.video_source === "telegram_channel" ? "Сообщение Telegram" : "Ссылка на видео"}</span><input value={form.video_reference ?? ""} placeholder={form.video_source === "telegram_channel" ? "-1001234567890:42" : "https://vimeo.com/…"} onChange={(event) => setForm({ ...form, video_reference: event.target.value || null })} />{form.video_source === "telegram_channel" && <small>Формат: ID канала:ID сообщения</small>}</label>
        {form.video_source === "external_url" && getVimeoEmbedUrl(form.video_reference) && <div className="course-form-grid__wide"><VimeoPreview url={form.video_reference} title={`Видео урока ${form.title || "без названия"}`} /></div>}
        <label><span>Задержка выдачи, часов</span><input type="number" min={0} value={form.release_offset_hours} onChange={(event) => setForm({ ...form, release_offset_hours: Number(event.target.value) })} /></label>
        <label className="switch-field switch-field--card"><input type="checkbox" checked={form.requires_view_confirmation} onChange={(event) => setForm({ ...form, requires_view_confirmation: event.target.checked })} /><span>Требовать подтверждение просмотра</span></label>
      </div>
      {materials.length > 0 && <section className="lesson-materials"><SectionTitle eyebrow="Материалы недели" title={`${materials.length} материалов`} /><div className="lesson-materials__grid">{materials.map((material) => <article key={material.material_id}><div className="lesson-materials__number">{material.position}</div>{material.kind === "video" && <VimeoPreview url={material.video_reference} title={material.title} />}{material.kind === "image" && material.video_reference && <a className="lesson-materials__image" href={`/${material.video_reference.replace("frontend/public/", "")}`} target="_blank" rel="noreferrer"><img loading="lazy" src={`/${material.video_reference.replace("frontend/public/", "")}`} alt={material.title} /></a>}<div className="lesson-materials__body"><strong>{material.title}</strong>{material.description && <p>{material.description}</p>}{material.kind === "video" && material.video_reference && <a href={material.video_reference} target="_blank" rel="noreferrer">Открыть видео ↗</a>}{material.kind === "image" && <span>Графический пример</span>}</div></article>)}</div></section>}
      <section className="assignment-editor">
        <SectionTitle eyebrow="Практика" title="Домашнее задание"><label className="switch-field"><input type="checkbox" checked={form.assignment !== null} onChange={(event) => setForm({ ...form, assignment: event.target.checked ? { instructions: "", submission_kind: "any", is_required: true } : null })} /><span>Есть ДЗ</span></label></SectionTitle>
        {form.assignment && <div className="course-form-grid"><label className="course-form-grid__wide"><span>Инструкция</span><textarea rows={4} value={form.assignment.instructions} onChange={(event) => setForm({ ...form, assignment: form.assignment ? { ...form.assignment, instructions: event.target.value } : null })} /></label><label><span>Формат ответа</span><select value={form.assignment.submission_kind} onChange={(event) => setForm({ ...form, assignment: form.assignment ? { ...form.assignment, submission_kind: event.target.value as NonNullable<LessonWrite["assignment"]>["submission_kind"] } : null })}><option value="any">Любой</option><option value="text">Текст</option><option value="file">Файл</option><option value="photo">Фото</option><option value="video">Видео</option></select></label><label className="switch-field switch-field--card"><input type="checkbox" checked={form.assignment.is_required} onChange={(event) => setForm({ ...form, assignment: form.assignment ? { ...form.assignment, is_required: event.target.checked } : null })} /><span>Обязательное задание</span></label></div>}
      </section>
      <FormActions hint={onDispatch ? "Урок опубликован — его можно выдать Discord-ученикам" : "Сначала сохрани и опубликуй урок"}>{onDispatch && <button type="button" className="discord-dispatch-link" onClick={onDispatch}>Выдать ДЗ в Discord</button>}<button className="course-save-button" disabled={busy}>{busy ? "Сохраняем…" : creating ? "Создать урок" : "Сохранить урок"}</button></FormActions>
    </form>
  );
}

function SectionTitle({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) { return <div className="course-builder__section-title"><div><span>{eyebrow}</span><h3>{title}</h3></div>{children}</div>; }
function FormActions({ hint, children }: { hint: string; children: React.ReactNode }) { return <div className="course-form-actions"><span>{hint}</span>{children}</div>; }
function emptyLesson(): LessonWrite { return { title: "", description: null, video_source: "placeholder", video_reference: null, release_offset_hours: 0, requires_view_confirmation: true, is_published: false, assignment: { instructions: "", submission_kind: "any", is_required: true } }; }
function lessonToForm(lesson: LessonContent): LessonWrite { return { title: lesson.title, description: lesson.description, video_source: lesson.video_source, video_reference: lesson.video_reference, release_offset_hours: lesson.release_offset_hours, requires_view_confirmation: lesson.requires_view_confirmation, is_published: lesson.is_published, assignment: lesson.assignment ? { ...lesson.assignment } : null }; }
function normalizeLesson(form: LessonWrite): LessonWrite { return { ...form, title: form.title.trim(), description: form.description?.trim() || null, video_reference: form.video_reference?.trim() || null, assignment: form.assignment ? { ...form.assignment, instructions: form.assignment.instructions.trim() } : null }; }
function unlockLabel(rule: CourseContent["unlock_rule"]): string { return { after_view: "После просмотра", after_submission: "После сдачи ДЗ", after_acceptance: "После принятия ДЗ" }[rule]; }
function errorMessage(error: unknown, fallback: string): string { return error instanceof APIError ? error.message : fallback; }
