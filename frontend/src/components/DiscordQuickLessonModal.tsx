import { useState } from "react";

import { APIError, createLesson } from "../api";
import type { CourseOverview, LessonContent, LessonWrite } from "../types";

interface DiscordQuickLessonModalProps {
  course: CourseOverview;
  onClose: () => void;
  onCreated: (lesson: LessonContent, published: boolean) => Promise<void>;
}

export function DiscordQuickLessonModal({
  course,
  onClose,
  onCreated,
}: DiscordQuickLessonModalProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [materialUrl, setMaterialUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(published: boolean) {
    if (!title.trim()) return setError("Укажи название урока");
    if (!instructions.trim()) return setError("Добавь текст домашнего задания");
    setBusy(true);
    setError(null);
    const payload: LessonWrite = {
      title: title.trim(),
      description: description.trim() || null,
      video_source: materialUrl.trim() ? "external_url" : "placeholder",
      video_reference: materialUrl.trim() || null,
      release_offset_hours: 0,
      requires_view_confirmation: false,
      is_published: published,
      assignment: {
        instructions: instructions.trim(),
        submission_kind: "any",
        is_required: true,
      },
    };
    try {
      const updated = await createLesson(course.course_id, payload);
      const lesson = updated.lessons.at(-1);
      if (!lesson) throw new Error("lesson-not-created");
      await onCreated(lesson, published);
    } catch (caught) {
      setError(caught instanceof APIError ? caught.message : "Не удалось создать урок");
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="discord-quick-lesson-modal">
      <button className="modal-close" onClick={onClose}>×</button>
      <header><p className="eyebrow">{course.title}</p><h2>Новый урок</h2><span>Заполни содержание и сразу выбери: оставить черновиком или перейти к выдаче.</span></header>
      <div className="discord-quick-lesson-form">
        <label><span>Название урока</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Например, Построение торгового плана" autoFocus /></label>
        <label><span>Короткое описание — необязательно</span><textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Что изучит ученик" /></label>
        <label><span>Домашнее задание</span><textarea rows={5} value={instructions} onChange={(event) => setInstructions(event.target.value)} placeholder="Что именно нужно выполнить и отправить в приватную ветку" /></label>
        <label><span>Ссылка на материал — необязательно</span><input value={materialUrl} onChange={(event) => setMaterialUrl(event.target.value)} placeholder="https://youtube.com/… или https://vimeo.com/…" /></label>
      </div>
      {error && <div className="form-error">{error}</div>}
      <footer><button type="button" onClick={onClose}>Отмена</button><button type="button" disabled={busy} onClick={() => void save(false)}>Сохранить черновик</button><button type="button" className="primary" disabled={busy} onClick={() => void save(true)}>{busy ? "Создаём…" : "Опубликовать и выбрать учеников →"}</button></footer>
    </section>
  </div>;
}
