import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  APIError,
  assignReview,
  getAttachmentPlayback,
  getFeedbackAttachmentPlayback,
  getReviewDetail,
  releaseReview,
} from "../api";
import type {
  ReviewAttachment,
  ReviewAttempt,
  ReviewDetail,
  ReviewQueueItem,
  ReviewVerdict,
  Staff,
} from "../types";

interface ReviewModalProps {
  item: ReviewQueueItem;
  staff: Staff;
  onChanged: () => Promise<void>;
  onClose: () => void;
  onDecision: (
    item: ReviewQueueItem,
    verdict: ReviewVerdict,
    message: string,
    attachment?: File | null,
  ) => Promise<void>;
}

export function ReviewModal({ item, staff, onChanged, onClose, onDecision }: ReviewModalProps) {
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [comment, setComment] = useState("");
  const [feedbackFile, setFeedbackFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyVerdict, setBusyVerdict] = useState<ReviewVerdict | null>(null);
  const [assignmentBusy, setAssignmentBusy] = useState(false);
  const isReviewed = item.status === "accepted" || item.status === "revision_requested";

  useEffect(() => {
    if (isReviewed) {
      return;
    }
    function handlePaste(event: ClipboardEvent) {
      const pasted = Array.from(event.clipboardData?.files ?? []).find((candidate) =>
        candidate.type.startsWith("image/"),
      );
      if (!pasted) {
        return;
      }
      event.preventDefault();
      const extension = pasted.type.split("/")[1] ?? "png";
      setFeedbackFile(
        new File([pasted], `Скриншот ${new Date().toLocaleString("ru-RU")}.${extension}`, {
          type: pasted.type,
        }),
      );
    }
    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [isReviewed]);

  useEffect(() => {
    let active = true;
    setDetail(null);
    setError(null);
    getReviewDetail(item.submission_id)
      .then((loadedDetail) => active && setDetail(loadedDetail))
      .catch((caughtError) => {
        if (active) {
          setError(
            caughtError instanceof APIError
              ? caughtError.message
              : "Не удалось загрузить работу",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [item.submission_id]);

  async function decide(verdict: ReviewVerdict) {
    const normalizedComment = comment.trim();
    if (!normalizedComment && !feedbackFile) {
      setError("Добавь комментарий или прикрепи файл для ученика");
      return;
    }
    setBusyVerdict(verdict);
    setError(null);
    try {
      await onDecision(item, verdict, normalizedComment, feedbackFile);
      onClose();
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось сохранить решение",
      );
    } finally {
      setBusyVerdict(null);
    }
  }

  async function handleAssign() {
    setAssignmentBusy(true);
    setError(null);
    try {
      await assignReview(item.submission_id);
      await onChanged();
      setDetail(await getReviewDetail(item.submission_id));
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось взять работу в проверку",
      );
    } finally {
      setAssignmentBusy(false);
    }
  }

  async function handleRelease() {
    setAssignmentBusy(true);
    setError(null);
    try {
      await releaseReview(item.submission_id);
      await onChanged();
      setDetail(await getReviewDetail(item.submission_id));
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Не удалось вернуть работу в очередь",
      );
    } finally {
      setAssignmentBusy(false);
    }
  }

  const resolved = detail ?? fallbackDetail(item);
  const discordSourceUrl = resolved.source === "discord"
    && resolved.source_guild_id
    && resolved.source_channel_id
    && resolved.source_message_id
    ? `https://discord.com/channels/${resolved.source_guild_id}/${resolved.source_channel_id}/${resolved.source_message_id}`
    : null;
  const assignedToMe = resolved.assigned_reviewer_id === staff.id;
  const assignedToOther =
    resolved.assigned_reviewer_id !== null && resolved.assigned_reviewer_id !== staff.id;
  const canDecide = !assignedToOther;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="review-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Работа ${item.student_name}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}>
          ×
        </button>
        <article className={`review-card review-card--${resolved.status}`}>
          <header className="review-card__header">
            <div className="student-block">
              <span className="student-avatar">{initials(resolved.student_name)}</span>
              <div>
                <h3>{resolved.student_name}</h3>
                <span>
                  {resolved.source === "discord"
                    ? "Discord-участник"
                    : resolved.student_username
                    ? `@${resolved.student_username}`
                    : "без username"}
                </span>
              </div>
            </div>
            <div className="submission-time">
              <span className="status-dot" />
              {formatDate(resolved.submitted_at)}
            </div>
          </header>

          <div className="lesson-strip">
            <span className="lesson-number">{resolved.lesson_position}</span>
            <div>
              <small>{resolved.course_title}</small>
              <strong>{resolved.lesson_title}</strong>
            </div>
            <span className="attempt-badge">Попытка {resolved.attempt_number}</span>
          </div>

          {!isReviewed && (
            <section className={`review-assignment ${assignedToOther ? "locked" : ""}`}>
              <div>
                <span>Проверка</span>
                <strong>
                  {assignedToMe
                    ? "Работа закреплена за вами"
                    : assignedToOther
                    ? `Проверяет: ${resolved.assigned_reviewer_name || "другой куратор"}`
                    : "Работа свободна"}
                </strong>
              </div>
              {assignedToMe ? (
                <button disabled={assignmentBusy} onClick={() => void handleRelease()}>
                  Вернуть в очередь
                </button>
              ) : (
                !assignedToOther && (
                  <button disabled={assignmentBusy} onClick={() => void handleAssign()}>
                    Взять в проверку
                  </button>
                )
              )}
            </section>
          )}

          <section className="review-lesson-details">
            <article>
              <span>Курс</span>
              <strong>{resolved.course_title}</strong>
            </article>
            <article>
              <span>Урок</span>
              <strong>{resolved.lesson_position}. {resolved.lesson_title}</strong>
            </article>
            <article>
              <span>Попытка</span>
              <strong>{resolved.attempt_number}</strong>
            </article>
            <article>
              <span>Источник</span>
              <strong>{resolved.source === "discord" ? "Discord" : "Telegram"}</strong>
            </article>
          </section>

          <div className="answer-panel">
            <div className="answer-panel__label">
              <span>Ответ ученика</span>
              {resolved.attachment_count > 0 && (
                <span>Вложений: {resolved.attachment_count}</span>
              )}
            </div>
            <p><LinkifiedText text={resolved.text_body || "Текстового ответа нет — работа приложена файлом."} /></p>
          </div>

          {detail?.feedback_message && (
            <section
              className={`review-decision-summary review-decision-summary--${detail.feedback_verdict}`}
            >
              <div>
                <span>Решение куратора</span>
                <strong>
                  {detail.feedback_verdict === "accepted"
                    ? "Работа принята"
                    : "Отправлено на доработку"}
                </strong>
              </div>
              <blockquote>{detail.feedback_message}</blockquote>
              <small>
                {detail.reviewer_name || "Куратор"}
                {detail.reviewed_at ? ` · ${formatDate(detail.reviewed_at)}` : ""}
              </small>
            </section>
          )}

          {detail && detail.feedback_attachments.length > 0 && (
            <section className="attachments-panel attachments-panel--feedback">
              <div className="attachments-panel__heading">
                <span>Вложения куратора</span>
                <small>Фото или файлы, приложенные к решению</small>
              </div>
              <div className="attachment-list">
                {detail.feedback_attachments.map((attachment) => (
                  <AttachmentCard
                    key={attachment.id}
                    submissionId={detail.submission_id}
                    attachment={attachment}
                    source={detail.source}
                    owner="curator"
                  />
                ))}
              </div>
            </section>
          )}

          {(detail === null || detail.attachments.length > 0) && (
            <section className="attachments-panel">
              <div className="attachments-panel__heading">
                <span>Вложения</span>
                <small>
                  Файлы загружены через {resolved.source === "discord" ? "Discord" : "Telegram"}
                </small>
              </div>
              {detail === null ? (
                <div className="attachment-skeleton">
                  {error || "Загружаем данные файлов…"}
                </div>
              ) : (
                <div className="attachment-list">
                  {detail.attachments.map((attachment) => (
                    <AttachmentCard
                      key={attachment.id}
                      submissionId={detail.submission_id}
                      attachment={attachment}
                      source={detail.source}
                      owner="student"
                    />
                  ))}
                </div>
              )}
            </section>
          )}

          {detail && detail.previous_attempts.length > 0 && (
            <section className="attempt-history">
              <header><div><span>История попыток</span><strong>Предыдущие ответы по этому уроку</strong></div><b>{detail.previous_attempts.length}</b></header>
              <div className="attempt-history__list">
                {detail.previous_attempts.map((attempt) => (
                  <PreviousAttemptCard key={attempt.submission_id} attempt={attempt} />
                ))}
              </div>
            </section>
          )}

          {!isReviewed && (
            <>
              <label className="feedback-field">
                <span>Комментарий ученику</span>
                <textarea
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Что получилось и что нужно исправить?"
                  rows={4}
                />
              </label>
              <label className="feedback-upload-field">
                <span>Файл к ответу — необязательно</span>
                <input
                  type="file"
                  accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.txt"
                  onChange={(event) => {
                    setFeedbackFile(event.target.files?.[0] ?? null);
                  }}
                />
                <small>
                  {feedbackFile
                    ? `Выбран файл: ${feedbackFile.name}`
                    : "Можно приложить фото с пометками, PDF или другой файл. " +
                      "Скриншот можно просто вставить: Ctrl+V."}
                </small>
                {feedbackFile && (
                  <button
                    type="button"
                    className="feedback-upload-field__clear"
                    onClick={() => setFeedbackFile(null)}
                  >
                    ✕ Убрать файл
                  </button>
                )}
              </label>
              {error && <div className="review-modal__error form-error">{error}</div>}
              <div className="review-actions">
                <button
                  className="revision-button"
                  disabled={busyVerdict !== null || !canDecide}
                  onClick={() => void decide("revision_requested")}
                >
                  {busyVerdict === "revision_requested"
                    ? "Сохраняем…"
                    : "На доработку"}
                </button>
                <button
                  className="accept-button"
                  disabled={busyVerdict !== null || !canDecide}
                  onClick={() => void decide("accepted")}
                >
                  {busyVerdict === "accepted" ? "Сохраняем…" : "Принять работу"}
                </button>
              </div>
            </>
          )}
          {isReviewed && error && (
            <div className="review-modal__error form-error">{error}</div>
          )}
          {discordSourceUrl && (
            <a className="discord-source-link" href={discordSourceUrl} target="_blank" rel="noreferrer">
              Открыть оригинал в Discord ↗
            </a>
          )}
        </article>
      </section>
    </div>
  );
}

function AttachmentCard({
  submissionId,
  attachment,
  source,
  owner = "student",
}: {
  submissionId: string;
  attachment: ReviewAttachment;
  source: ReviewQueueItem["source"];
  owner?: "student" | "curator";
}) {
  const [playbackUrl, setPlaybackUrl] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [imageExpanded, setImageExpanded] = useState(false);
  const isVideo = attachment.kind === "video" || attachment.kind === "video_note";
  const isPhoto = attachment.kind === "photo";

  useEffect(() => {
    if (!isPhoto || !attachment.source_available) return;
    let active = true;
    setIsLoading(true);
    setError(null);
    setImageFailed(false);
    const loadPlayback = owner === "curator"
      ? getFeedbackAttachmentPlayback
      : getAttachmentPlayback;
    loadPlayback(submissionId, attachment.id)
      .then((playback) => active && setPlaybackUrl(playback.url))
      .catch((caughtError) => active && setError(
        caughtError instanceof APIError ? caughtError.message : "Изображение временно недоступно",
      ))
      .finally(() => active && setIsLoading(false));
    return () => { active = false; };
  }, [attachment.id, attachment.source_available, isPhoto, owner, submissionId]);

  async function openVideo() {
    setIsLoading(true);
    setError(null);
    try {
      const loadPlayback = owner === "curator"
        ? getFeedbackAttachmentPlayback
        : getAttachmentPlayback;
      const playback = await loadPlayback(submissionId, attachment.id);
      setPlaybackUrl(playback.url);
    } catch (caughtError) {
      setError(
        caughtError instanceof APIError
          ? caughtError.message
          : "Видео временно недоступно",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <article className={`attachment-card attachment-card--${attachment.kind}`}>
      {isPhoto && isLoading && <div className="photo-preview photo-preview--loading">Загружаем изображение…</div>}
      {isPhoto && playbackUrl && !imageFailed && (
        <button type="button" className="photo-preview" onClick={() => setImageExpanded(true)}>
          <img
            src={playbackUrl}
            alt={attachment.file_name || "Работа ученика"}
            onError={() => {
              setImageFailed(true);
              setError(source === "discord"
                ? "Discord-ссылка на изображение недоступна или истекла. Открой оригинал сообщения в Discord."
                : "Изображение временно недоступно.");
            }}
          />
          <span>Нажмите, чтобы увеличить</span>
        </button>
      )}
      {isPhoto && playbackUrl && imageFailed && (
        <div className="photo-preview photo-preview--error">
          <strong>Не удалось открыть изображение</strong>
          <span>{source === "discord" ? "Файл есть в работе, но Discord CDN не отдал preview." : "Источник изображения временно недоступен."}</span>
        </div>
      )}
      {isPhoto && playbackUrl && imageExpanded && createPortal(
        <div className="attachment-lightbox" role="dialog" aria-modal="true" onMouseDown={() => setImageExpanded(false)}>
          <button type="button" aria-label="Закрыть" onClick={() => setImageExpanded(false)}>×</button>
          <img src={playbackUrl} alt={attachment.file_name || "Работа ученика"} onMouseDown={(event) => event.stopPropagation()} />
        </div>,
        document.body,
      )}
      {isVideo && playbackUrl && (
        <div className="video-player">
          <video src={playbackUrl} controls autoPlay playsInline />
        </div>
      )}
      {isVideo && !playbackUrl && (
        <button
          type="button"
          className="video-preview"
          onClick={() => void openVideo()}
          disabled={isLoading || !attachment.source_available}
        >
          <span className="video-preview__play">▶</span>
          <span className="video-preview__format">
            {attachment.mime_type || "video"}
          </span>
          {attachment.duration_seconds && (
            <span className="video-preview__duration">
              {formatDuration(attachment.duration_seconds)}
            </span>
          )}
        </button>
      )}
      <div className="attachment-card__details">
        <span className={`attachment-card__icon attachment-card__icon--${attachment.kind}`}>
          {attachmentIcon(attachment.kind)}
        </span>
        <div>
          <strong>{attachment.file_name || attachmentLabel(attachment.kind)}</strong>
          <span>{attachmentMeta(attachment)}</span>
        </div>
        <span className="attachment-source">
          {attachment.source_available
            ? source === "discord" ? "Discord" : "Telegram"
            : "Источник недоступен"}
        </span>
      </div>
      {error && <div className="video-player__state video-player__state--error">{error}</div>}
    </article>
  );
}

function LinkifiedText({ text }: { text: string }) {
  const urlPattern = /(https?:\/\/[^\s]+)/g;
  return <>{text.split(urlPattern).map((part, index) => part.match(urlPattern)
    ? <a key={`${part}-${index}`} href={part} target="_blank" rel="noreferrer">{part}</a>
    : part)}</>;
}

function fallbackDetail(item: ReviewQueueItem): ReviewDetail {
  return {
    ...item,
    reviewed_at: null,
    feedback_verdict: null,
    feedback_message: null,
    reviewer_name: null,
    attachments: [],
    feedback_attachments: [],
    previous_attempts: [],
  };
}

function PreviousAttemptCard({ attempt }: { attempt: ReviewAttempt }) {
  const [open, setOpen] = useState(false);
  return <article className={`attempt-history__item ${open ? "open" : ""}`}>
    <button type="button" onClick={() => setOpen((value) => !value)}>
      <span><strong>Попытка {attempt.attempt_number}</strong><small>{formatDate(attempt.submitted_at)}</small></span>
      <em className={`attempt-history__status attempt-history__status--${attempt.status}`}>{historyStatus(attempt.status)}</em>
      <i>{open ? "−" : "+"}</i>
    </button>
    {open && <div className="attempt-history__content">
      <section><span>Ответ ученика</span><p><LinkifiedText text={attempt.text_body || "Текстового ответа нет — работа приложена файлом."} /></p></section>
      {attempt.attachments.length > 0 && <div className="attachment-list">{attempt.attachments.map((attachment) => <AttachmentCard key={attachment.id} submissionId={attempt.submission_id} attachment={attachment} source={attempt.source} owner="student" />)}</div>}
      {attempt.feedback_message && <section className="attempt-history__feedback"><span>Комментарий куратора</span><strong>{attempt.feedback_verdict === "accepted" ? "Работа принята" : "Отправлено на доработку"}</strong><p>{attempt.feedback_message}</p>{attempt.reviewer_name && <small>{attempt.reviewer_name}</small>}</section>}
      {attempt.feedback_attachments.length > 0 && <div className="attachment-list">{attempt.feedback_attachments.map((attachment) => <AttachmentCard key={attachment.id} submissionId={attempt.submission_id} attachment={attachment} source={attempt.source} owner="curator" />)}</div>}
    </div>}
  </article>;
}

function historyStatus(status: ReviewAttempt["status"]) {
  return {
    submitted: "Ожидает проверки",
    in_review: "На проверке",
    revision_requested: "На доработке",
    accepted: "Принята",
  }[status];
}

function attachmentLabel(kind: ReviewAttachment["kind"]): string {
  return {
    document: "Документ",
    photo: "Фотография",
    video: "Видео",
    video_note: "Видеосообщение",
  }[kind];
}

function attachmentIcon(kind: ReviewAttachment["kind"]): string {
  return {
    document: "DOC",
    photo: "IMG",
    video: "▶",
    video_note: "▶",
  }[kind];
}

function attachmentMeta(attachment: ReviewAttachment): string {
  const parts: string[] = [];
  if (attachment.mime_type) parts.push(attachment.mime_type.replace("application/", ""));
  if (attachment.width && attachment.height) {
    parts.push(`${attachment.width}×${attachment.height}`);
  }
  if (attachment.file_size) parts.push(formatBytes(attachment.file_size));
  return parts.join(" · ") || "Метаданные файла";
}

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} КБ`
    : `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}

function formatDuration(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}
