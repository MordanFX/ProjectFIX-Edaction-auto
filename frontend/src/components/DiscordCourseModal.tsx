import { useEffect, useState } from "react";

import {
  APIError,
  copyLessonFromKnowledge,
  createLesson,
  getCourse,
  updateLesson,
} from "../api";
import type { CourseContent, CourseOverview, LessonContent, LessonWrite } from "../types";
import { LessonImportModal } from "./LessonImportModal";

interface DiscordCourseModalProps {
  overview: CourseOverview;
  knowledgeCourses: CourseOverview[];
  onClose: () => void;
  onChanged: () => Promise<void>;
  onDispatchLesson: (courseId: string, lessonId: string) => void;
}

interface LessonForm {
  title: string;
  description: string;
  materialUrl: string;
  instructions: string;
}

const emptyForm: LessonForm = {
  title: "",
  description: "",
  materialUrl: "",
  instructions: "",
};

export function DiscordCourseModal({
  overview,
  knowledgeCourses,
  onClose,
  onChanged,
  onDispatchLesson,
}: DiscordCourseModalProps) {
  const [course, setCourse] = useState<CourseContent | null>(null);
  const [selectedLessonId, setSelectedLessonId] = useState<string | null>(null);
  const [form, setForm] = useState<LessonForm>(emptyForm);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getCourse(overview.course_id)
      .then((loaded) => {
        if (!active) return;
        setCourse(loaded);
        if (loaded.lessons[0]) selectLesson(loaded.lessons[0]);
        else startCreating();
      })
      .catch((caught) => active && setError(errorMessage(caught, "Не удалось загрузить курс")));
    return () => { active = false; };
  }, [overview.course_id]);

  function selectLesson(lesson: LessonContent) {
    setSelectedLessonId(lesson.lesson_id);
    setCreating(false);
    setForm({
      title: lesson.title,
      description: lesson.description || "",
      materialUrl: lesson.video_source === "external_url" ? lesson.video_reference || "" : "",
      instructions: lesson.assignment?.instructions || "",
    });
    setError(null);
    setNotice(null);
  }

  function startCreating() {
    setSelectedLessonId(null);
    setCreating(true);
    setForm(emptyForm);
    setError(null);
    setNotice(null);
  }

  async function save(published: boolean) {
    if (!course) return;
    if (!form.title.trim()) return setError("Укажи название урока");
    if (!form.instructions.trim()) return setError("Добавь текст домашнего задания");
    const payload: LessonWrite = {
      title: form.title.trim(),
      description: form.description.trim() || null,
      video_source: form.materialUrl.trim() ? "external_url" : "placeholder",
      video_reference: form.materialUrl.trim() || null,
      release_offset_hours: 0,
      requires_view_confirmation: false,
      is_published: published,
      assignment: {
        instructions: form.instructions.trim(),
        submission_kind: "any",
        is_required: true,
      },
    };
    setBusy(true);
    setError(null);
    try {
      const updated = selectedLessonId
        ? await updateLesson(course.course_id, selectedLessonId, payload)
        : await createLesson(course.course_id, payload);
      setCourse(updated);
      const saved = selectedLessonId
        ? updated.lessons.find((lesson) => lesson.lesson_id === selectedLessonId)
        : updated.lessons.at(-1);
      if (saved) selectLesson(saved);
      setNotice(published ? "Урок опубликован" : "Черновик сохранён");
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught, "Не удалось сохранить урок"));
    } finally {
      setBusy(false);
    }
  }

  async function importLesson(sourceLessonId: string) {
    if (!course) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await copyLessonFromKnowledge(course.course_id, sourceLessonId);
      setCourse(updated);
      const imported = updated.lessons.at(-1);
      if (imported) selectLesson(imported);
      setNotice("Урок добавлен из базы знаний");
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught, "Не удалось добавить урок из базы знаний"));
      throw caught;
    } finally {
      setBusy(false);
    }
  }

  const selectedLesson = course?.lessons.find((lesson) => lesson.lesson_id === selectedLessonId) || null;

  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section className="discord-course-modal" onMouseDown={(event) => event.stopPropagation()}>
      <button className="modal-close" onClick={onClose}>×</button>
      {!course ? <div className="discord-course-loading">{error || "Загружаем Discord-курс…"}</div> : <>
        <header className="discord-course-header">
          <div><span>Discord-курс</span><h2>{course.title}</h2><p>{course.description || "Описание курса не заполнено"}</p></div>
          <div className="discord-course-header__stats"><span><b>{course.lessons.length}</b> уроков</span><span><b>{overview.students_count}</b> учеников</span></div>
        </header>

        <div className="discord-course-stage"><b>1</b><div><strong>Уроки и домашние задания</strong><span>Все уроки видны всегда. Черновики отмечены отдельно и не попадают в рассылку.</span></div></div>

        <div className="discord-course-workspace">
          <aside>
            <div className="discord-course-sidebar-title"><div><span>Содержание</span><strong>Уроки</strong></div><button type="button" onClick={startCreating}>+</button></div>
            <div className="discord-course-lesson-list">
              {course.lessons.map((lesson) => <button type="button" className={selectedLessonId === lesson.lesson_id ? "active" : ""} key={lesson.lesson_id} onClick={() => selectLesson(lesson)}><b>{lesson.position}</b><span><strong>{lesson.title}</strong><small className={lesson.is_published ? "published" : "draft"}>{lesson.is_published ? "Опубликован" : "Черновик"}</small></span></button>)}
              {!course.lessons.length && <div className="discord-course-no-lessons">Уроков пока нет</div>}
            </div>
            <button type="button" className="discord-course-new-lesson" onClick={startCreating}>+ Создать урок</button>
            <button type="button" className="discord-course-new-lesson secondary" onClick={() => setImportOpen(true)}>Выбрать из базы знаний</button>
          </aside>

          <section className="discord-course-editor">
            <header><div><span>{creating ? "Новый урок" : `Урок ${selectedLesson?.position}`}</span><h3>{creating ? "Создание урока" : "Редактирование урока"}</h3></div>{selectedLesson && <span className={`discord-lesson-state ${selectedLesson.is_published ? "published" : "draft"}`}>{selectedLesson.is_published ? "Опубликован" : "Черновик"}</span>}</header>
            <div className="discord-course-editor__fields">
              <label><span>Название урока</span><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="Название урока" /></label>
              <label><span>Описание — необязательно</span><textarea rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Коротко о содержании урока" /></label>
              <label><span>Ссылка на материал — необязательно</span><input value={form.materialUrl} onChange={(event) => setForm({ ...form, materialUrl: event.target.value })} placeholder="https://youtube.com/… или https://vimeo.com/…" /></label>
              <label className="homework"><span>Домашнее задание</span><textarea rows={5} value={form.instructions} onChange={(event) => setForm({ ...form, instructions: event.target.value })} placeholder="Что ученик должен выполнить и отправить в приватную ветку" /></label>
            </div>
            {error && <div className="form-error">{error}</div>}
            {notice && <div className="discord-course-notice">✓ {notice}</div>}
            <footer>
              {selectedLesson?.is_published && <button type="button" className="dispatch" onClick={() => onDispatchLesson(course.course_id, selectedLesson.lesson_id)}>Перейти к выдаче ДЗ →</button>}
              <span />
              <button type="button" disabled={busy} onClick={() => void save(false)}>{selectedLesson?.is_published ? "Снять с публикации" : "Сохранить черновик"}</button>
              <button type="button" className="primary" disabled={busy} onClick={() => void save(true)}>{busy ? "Сохраняем…" : selectedLesson?.is_published ? "Сохранить изменения" : "Опубликовать урок"}</button>
            </footer>
          </section>
        </div>
        {importOpen && (
          <LessonImportModal
            courses={knowledgeCourses}
            targetCourseId={course.course_id}
            onClose={() => setImportOpen(false)}
            onImport={importLesson}
          />
        )}
      </>}
    </section>
  </div>;
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof APIError ? error.message : fallback;
}
