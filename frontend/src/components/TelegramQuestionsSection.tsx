import { useEffect, useRef, useState } from "react";

import {
  answerTelegramQuestion,
  APIError,
  getTelegramQuestionAttachmentPlayback,
  getTelegramQuestions,
  resolveTelegramQuestion,
} from "../api";
import type { AttachmentKind, TelegramQuestion, TelegramQuestionAttachment } from "../types";

export function TelegramQuestionsSection({ onRefresh }: { onRefresh?: () => Promise<void> }) {
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

  async function afterChange() {
    await loadQuestions();
    if (onRefresh) await onRefresh();
  }

  async function resolve(questionId: string) {
    await resolveTelegramQuestion(questionId);
    await afterChange();
  }

  async function answer(questionId: string, message: string, files: File[]) {
    await answerTelegramQuestion(questionId, message, files);
    await afterChange();
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
              <QuestionRow
                key={question.question_id}
                question={question}
                onResolve={resolve}
                onAnswer={answer}
              />
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

function QuestionRow({ question, onResolve, onAnswer }: {
  question: TelegramQuestion;
  onResolve: (questionId: string) => Promise<void>;
  onAnswer: (questionId: string, message: string, files: File[]) => Promise<void>;
}) {
  const [answering, setAnswering] = useState(false);
  const [answerText, setAnswerText] = useState("");
  const [answerFiles, setAnswerFiles] = useState<File[]>([]);
  const [answerSaving, setAnswerSaving] = useState(false);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lessonLabel = question.lesson_title
    ? `Урок ${question.lesson_position ?? "?"}: ${question.lesson_title}`
    : "Урок не определён";
  const studentAttachments = question.attachments.filter((item) => item.source === "student");
  const curatorAttachments = question.attachments.filter((item) => item.source === "curator");

  async function submitAnswer() {
    if (!answerText.trim() && answerFiles.length === 0) return;
    setAnswerSaving(true);
    setAnswerError(null);
    try {
      await onAnswer(question.question_id, answerText.trim(), answerFiles);
      setAnswering(false);
      setAnswerText("");
      setAnswerFiles([]);
    } catch (caughtError) {
      setAnswerError(
        caughtError instanceof APIError ? caughtError.message : "Не удалось отправить ответ",
      );
    } finally {
      setAnswerSaving(false);
    }
  }

  return (
    <article>
      <div className="discord-question-list__main">
        <span className="discord-submission-list__avatar">{initials(question.student_name)}</span>
        <div>
          <strong>{question.student_name}{question.student_username ? ` · @${question.student_username}` : ""}</strong>
          <small>{formatShortDate(question.created_at)} · {lessonLabel}{question.course_title ? ` · ${question.course_title}` : ""}</small>
          <p>{question.text_body || (studentAttachments.length ? "Без текста, смотри вложение." : "Пустой вопрос.")}</p>
          {studentAttachments.length > 0 && (
            <div className="telegram-question-attachments">
              {studentAttachments.map((attachment) => (
                <AttachmentLink
                  key={attachment.id}
                  questionId={question.question_id}
                  attachment={attachment}
                />
              ))}
            </div>
          )}
          {question.status === "resolved" && (
            <>
              {question.answer_text && <p className="telegram-question-answer">↳ {question.answer_text}</p>}
              {curatorAttachments.length > 0 && (
                <div className="telegram-question-attachments telegram-question-attachments--answer">
                  {curatorAttachments.map((attachment) => (
                    <AttachmentLink
                      key={attachment.id}
                      questionId={question.question_id}
                      attachment={attachment}
                    />
                  ))}
                </div>
              )}
              <em>Закрыто: {question.resolved_by || "куратор"}{question.resolved_at ? ` · ${formatShortDate(question.resolved_at)}` : ""}</em>
            </>
          )}
          {answering && (
            <div className="telegram-question-answer-form feedback-field">
              <textarea
                value={answerText}
                onChange={(event) => setAnswerText(event.target.value)}
                placeholder="Ответ ученику, уйдёт ему в Telegram"
                rows={3}
                disabled={answerSaving}
              />
              {answerFiles.length > 0 && (
                <ul className="telegram-question-answer-form__files">
                  {answerFiles.map((file, index) => (
                    <li key={`${file.name}-${index}`}>
                      {file.name}
                      <button
                        type="button"
                        onClick={() => setAnswerFiles((files) => files.filter((_, i) => i !== index))}
                        disabled={answerSaving}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <input
                ref={fileInputRef}
                type="file"
                multiple
                hidden
                onChange={(event) => {
                  const picked = Array.from(event.target.files ?? []);
                  if (picked.length) setAnswerFiles((files) => [...files, ...picked]);
                  event.target.value = "";
                }}
              />
              {answerError && <div className="form-error">{answerError}</div>}
              <div className="telegram-question-answer-form__actions">
                <button
                  type="button"
                  className="telegram-question-answer-form__attach"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={answerSaving}
                >
                  📎 Прикрепить файл
                </button>
                <button type="button" onClick={() => { setAnswering(false); setAnswerError(null); setAnswerFiles([]); }} disabled={answerSaving}>
                  Отмена
                </button>
                <button
                  type="button"
                  onClick={() => void submitAnswer()}
                  disabled={answerSaving || (!answerText.trim() && answerFiles.length === 0)}
                >
                  {answerSaving ? "Отправляем…" : "Отправить ответ"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <div className="discord-question-list__actions">
        <b className={`discord-work-status discord-work-status--${question.status}`}>
          {question.status === "open" ? "Открыт" : "Закрыт"}
        </b>
        {question.status === "open" && !answering && (
          <button onClick={() => setAnswering(true)}>Ответить</button>
        )}
        {question.status === "open" && (
          <button onClick={() => void onResolve(question.question_id)}>Закрыть вопрос</button>
        )}
      </div>
    </article>
  );
}

function AttachmentLink({ questionId, attachment }: {
  questionId: string;
  attachment: TelegramQuestionAttachment;
}) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open() {
    setOpening(true);
    setError(null);
    try {
      const playback = await getTelegramQuestionAttachmentPlayback(questionId, attachment.id);
      window.open(playback.url, "_blank", "noopener");
    } catch (caughtError) {
      setError(caughtError instanceof APIError ? caughtError.message : "Вложение недоступно");
    } finally {
      setOpening(false);
    }
  }

  return (
    <span className="telegram-question-attachments__item">
      <button type="button" onClick={() => void open()} disabled={opening}>
        {opening ? "Открываем…" : `📎 ${attachment.file_name || attachmentKindLabel(attachment.kind)}`}
      </button>
      {error && <em>{error}</em>}
    </span>
  );
}

function attachmentKindLabel(kind: AttachmentKind) {
  return { photo: "Фото", document: "Файл", video: "Видео", video_note: "Видео" }[kind];
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
