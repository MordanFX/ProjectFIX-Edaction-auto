import { FormEvent, useState } from "react";

import { APIError, createCourse } from "../api";

interface CourseCreatePanelProps {
  onCreated: () => Promise<void>;
}

export function CourseCreatePanel({ onCreated }: CourseCreatePanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [audience, setAudience] = useState<"telegram" | "discord">("telegram");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedTitle = title.trim();
    if (!normalizedTitle) {
      setError("Укажи название курса");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      await createCourse({
        title: normalizedTitle,
        description: description.trim() || null,
        is_active: isActive,
        audience,
      });
      await onCreated();
      setTitle("");
      setDescription("");
      setIsActive(true);
      setAudience("telegram");
      setIsOpen(false);
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось создать курс",
      );
    } finally {
      setIsSaving(false);
    }
  }

  if (!isOpen) {
    return (
      <section className="course-create-prompt">
        <div>
          <span>Новая программа</span>
          <strong>Создать курс с нуля</strong>
          <p>После создания добавь группы, уроки и домашние задания.</p>
        </div>
        <button type="button" onClick={() => setIsOpen(true)}>
          + Создать курс
        </button>
      </section>
    );
  }

  return (
    <form className="course-create-panel" onSubmit={handleSubmit}>
      <div className="course-create-panel__heading">
        <div>
          <span>Новая программа</span>
          <h2>Основные данные курса</h2>
        </div>
        <button type="button" onClick={() => setIsOpen(false)} aria-label="Закрыть">
          ×
        </button>
      </div>
      <div className="course-create-panel__fields">
        <label>
          <span>Название</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={255}
            placeholder="Например, Основы трейдинга"
            autoFocus
          />
        </label>
        <label className="course-create-panel__description">
          <span>Описание</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            rows={3}
            placeholder="Коротко опиши результат обучения"
          />
        </label>
        <label>
          <span>Поток учеников</span>
          <select
            value={audience}
            onChange={(event) =>
              setAudience(event.target.value as "telegram" | "discord")
            }
          >
            <option value="telegram">Telegram</option>
            <option value="discord">Discord</option>
          </select>
        </label>
        <label className="course-create-panel__switch">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.target.checked)}
          />
          <span>Сразу сделать курс активным</span>
        </label>
      </div>
      {error && <div className="form-error">{error}</div>}
      <div className="course-create-panel__actions">
        <button type="button" onClick={() => setIsOpen(false)}>
          Отмена
        </button>
        <button className="course-save-button" disabled={isSaving}>
          {isSaving ? "Создаём…" : "Создать курс"}
        </button>
      </div>
    </form>
  );
}
