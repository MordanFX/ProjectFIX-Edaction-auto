import { useEffect, useState } from "react";

import { APIError, getTelegramQuestionAttachmentPlayback, getTelegramQuestions, resolveTelegramQuestion } from "../api";
import type { TelegramQuestion } from "../types";

export function TelegramQuestionsSection() {
  const [questions, setQuestions] = useState<TelegramQuestion[]>([]);
  const [filter, setFilter] = useState<"open" | "all" | "resolved">("open");
  const openQuestions = questions.filter((question) => question.status === "open");
  const filtered = questions.filter((question) =>
    filter === "all" ? true : question.status === filter,
  );

  async function loadQuestions() {
    setQuestions(await getTelegramQuestions());
  }

  useEffect(() => {
    void loadQuestions();
  }, []);

  async function resolve(questionId: string) {
    await resolveTelegramQuestion(questionId);
    await loadQuestions();
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Коммуникация</p>
          <h1>Вопросы куратору</h1>
          <p className="muted">Обращения учеников из Telegram-бота (кнопка «Уточнить у куратора»).</p>
        </div>
      </div>

      <div className="discord-compact-summary">
        <article><span>Открыто</span><b>{openQuestions.length}</b><small>Нужен ответ куратора</small></article>
        <article><span>Всего</span><b>{questions.length}</b><small>За всё время</small></article>
      </div>

      <section className="discord-board">
        <header>
          <div><p className="eyebrow">Очередь</p><h2>Вопросы от учеников</h2></div>
          <div className="discord-board-actions">
            <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
              <option value="open">Открытые</option>
              <option value="resolved">Закрытые</option>
              <option value="all">Все вопросы</option>
            </select>
            <button className="secondary-button" onClick={() => void loadQuestions()}>↻ Обновить</button>
          </div>
        </header>
        {filtered.length ? (
          <div className="discord-question-list">
            {filtered.map((question) => (
              <QuestionRow key={question.question_id} question={question} onResolve={resolve} />
            ))}
          </div>
        ) : (
          <div className="discord-empty">
            <strong>Вопросов нет</strong>
            <span>Когда ученик нажмёт «Уточнить у куратора» в боте, обращение появится здесь.</span>
          </div>
        )}
      </section>
    </>
  );
}

function QuestionRow({ question, onResolve }: {
  question: TelegramQuestion;
  onResolve: (questionId: string) => Promise<void>;
}) {
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const lessonLabel = question.lesson_title
    ? `Урок ${question.lesson_position ?? "?"}: ${question.lesson_title}`
    : "Урок не определён";

  async function openAttachment() {
    setOpening(true);
    setAttachmentError(null);
    try {
      const playback = await getTelegramQuestionAttachmentPlayback(question.question_id);
      window.open(playback.url, "_blank", "noopener");
    } catch (caughtError) {
      setAttachmentError(
        caughtError instanceof APIError ? caughtError.message : "Вложение временно недоступно",
      );
    } finally {
      setOpening(false);
    }
  }

  return (
    <article>
      <div className="discord-question-list__main">
        <span className="discord-submission-list__avatar">{initials(question.student_name)}</span>
        <div>
          <strong>{question.student_name}{question.student_username ? ` · @${question.student_username}` : ""}</strong>
          <small>{formatShortDate(question.created_at)} · {lessonLabel}{question.course_title ? ` · ${question.course_title}` : ""}</small>
          <p>{question.text_body || (question.has_attachment ? "Без текста, смотри вложение." : "Пустой вопрос.")}</p>
          {attachmentError && <em>{attachmentError}</em>}
          {question.status === "resolved" && (
            <>
              {question.answer_text && <p className="telegram-question-answer">↳ {question.answer_text}</p>}
              <em>Закрыто: {question.resolved_by || "куратор"}{question.resolved_at ? ` · ${formatShortDate(question.resolved_at)}` : ""}</em>
            </>
          )}
        </div>
      </div>
      <div className="discord-question-list__actions">
        <b className={`discord-work-status discord-work-status--${question.status}`}>
          {question.status === "open" ? "Открыт" : "Закрыт"}
        </b>
        {question.has_attachment && (
          <button onClick={() => void openAttachment()} disabled={opening}>
            {opening ? "Открываем…" : "Вложение ↗"}
          </button>
        )}
        {question.status === "open" && (
          <button onClick={() => void onResolve(question.question_id)}>Закрыть вопрос</button>
        )}
      </div>
    </article>
  );
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
