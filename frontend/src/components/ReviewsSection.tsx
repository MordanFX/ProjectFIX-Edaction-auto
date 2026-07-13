import { useMemo, useState } from "react";

import type {
  AttachmentKind,
  DashboardSummary,
  ReviewQueueItem,
} from "../types";

type ReviewFilter = "all" | "pending" | "reviewed";

interface ReviewsSectionProps {
  queue: ReviewQueueItem[];
  summary: DashboardSummary;
  onRefresh: () => Promise<void>;
  onSelect: (item: ReviewQueueItem) => void;
}

export function ReviewsSection({
  queue,
  summary,
  onRefresh,
  onSelect,
}: ReviewsSectionProps) {
  const [filter, setFilter] = useState<ReviewFilter>("all");
  const pending = useMemo(
    () => queue.filter((item) => isPending(item)),
    [queue],
  );
  const reviewed = useMemo(
    () => queue.filter((item) => !isPending(item)),
    [queue],
  );
  const visible =
    filter === "pending" ? pending : filter === "reviewed" ? reviewed : queue;
  const studentGroups = groupByStudent(visible);
  const receivedToday = queue.filter(
    (item) =>
      new Date(item.submitted_at).toDateString() === new Date().toDateString(),
  ).length;

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Telegram-поток</p>
          <h1>Домашние задания Telegram</h1>
          <p className="muted">
            Новые и уже проверенные работы остаются в общей истории.
          </p>
        </div>
        <button className="secondary-button" onClick={() => void onRefresh()}>
          ↻ Обновить
        </button>
      </div>

      <div className="metrics-grid">
        <MetricCard
          label="Ожидают проверки"
          value={summary.pending_reviews}
          accent
        />
        <MetricCard label="Поступили сегодня" value={receivedToday} />
        <MetricCard
          label="Статус очереди"
          value={pending.length ? "В работе" : "Чисто"}
        />
      </div>

      <div className="review-filters">
        <span>Показать работы</span>
        <FilterButton
          active={filter === "pending"}
          count={pending.length}
          onClick={() => setFilter("pending")}
        >
          Ожидают
        </FilterButton>
        <FilterButton
          active={filter === "reviewed"}
          count={reviewed.length}
          onClick={() => setFilter("reviewed")}
        >
          Проверены
        </FilterButton>
        <FilterButton
          active={filter === "all"}
          count={queue.length}
          onClick={() => setFilter("all")}
        >
          Все
        </FilterButton>
      </div>

      {visible.length ? (
        <section className="review-board">
          <div className="review-board__heading">
            <div>
              <p className="eyebrow">Работы</p>
              <h2>{filterTitle(filter)}</h2>
            </div>
            <span>
              {studentCount(studentGroups.length)} · {workCount(visible.length)}
            </span>
          </div>
          <div className="review-student-grid">
            {studentGroups.map((group) => (
              <StudentReviewCard
                key={group.studentId}
                group={group}
                onSelect={onSelect}
              />
            ))}
          </div>
        </section>
      ) : (
        <section className="review-filter-empty">
          {filter === "pending"
            ? "Сейчас нет работ, ожидающих проверки."
            : "В этом разделе пока нет работ."}
        </section>
      )}
    </>
  );
}

function FilterButton({
  active,
  count,
  onClick,
  children,
}: {
  active: boolean;
  count: number;
  onClick: () => void;
  children: string;
}) {
  return (
    <button type="button" className={active ? "active" : ""} onClick={onClick}>
      {children} <b>{count}</b>
    </button>
  );
}

function MetricCard({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string | number;
  accent?: boolean;
}) {
  return (
    <article className={`metric-card ${accent ? "metric-card--accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

interface StudentReviewGroup {
  studentId: string;
  studentName: string;
  studentUsername: string | null;
  items: ReviewQueueItem[];
}

function StudentReviewCard({
  group,
  onSelect,
}: {
  group: StudentReviewGroup;
  onSelect: (item: ReviewQueueItem) => void;
}) {
  const pendingCount = group.items.filter(isPending).length;
  return (
    <article className="student-review-card">
      <header>
        <span className="student-avatar">{initials(group.studentName)}</span>
        <div>
          <strong>{group.studentName}</strong>
          <small>
            {group.studentUsername ? `@${group.studentUsername}` : "без username"}
          </small>
        </div>
        <span className={pendingCount ? "has-pending" : ""}>
          {pendingCount ? `${pendingCount} ожидают` : "всё проверено"}
        </span>
      </header>
      <div className="student-review-card__summary">
        <span>{workCount(group.items.length)}</span>
        <span>{group.items[0]?.course_title}</span>
      </div>
      <div className="student-review-card__works">
        {group.items.map((item) => (
          <button
            type="button"
            className={`student-review-work student-review-work--${item.status}`}
            key={item.submission_id}
            onClick={() => onSelect(item)}
          >
            <span className="student-review-work__icon">
              {attachmentIcon(item.attachment_kind)}
            </span>
            <span className="student-review-work__lesson">
              <strong>
                Урок {item.lesson_position} · {item.lesson_title}
              </strong>
              <small>
                {formatDate(item.submitted_at)} · попытка {item.attempt_number}
              </small>
            </span>
            <span className="student-review-work__status">
              {statusLabel(item)}
            </span>
            <span className="student-review-work__action">Открыть →</span>
          </button>
        ))}
      </div>
    </article>
  );
}

function groupByStudent(items: ReviewQueueItem[]): StudentReviewGroup[] {
  const groups = new Map<string, StudentReviewGroup>();
  for (const item of items) {
    const studentKey = item.student_id || item.student_username || item.student_name;
    const group = groups.get(studentKey);
    if (group) {
      group.items.push(item);
    } else {
      groups.set(studentKey, {
        studentId: studentKey,
        studentName: item.student_name,
        studentUsername: item.student_username,
        items: [item],
      });
    }
  }
  return [...groups.values()]
    .map((group) => ({
      ...group,
      items: group.items.sort(
        (left, right) =>
          new Date(right.submitted_at).getTime() -
          new Date(left.submitted_at).getTime(),
      ),
    }))
    .sort((left, right) => {
      const leftPending = left.items.some(isPending) ? 1 : 0;
      const rightPending = right.items.some(isPending) ? 1 : 0;
      return rightPending - leftPending;
    });
}

function isPending(item: ReviewQueueItem): boolean {
  return item.status === "submitted" || item.status === "in_review";
}

function statusLabel(item: ReviewQueueItem): string {
  return {
    submitted: "Ожидает",
    in_review: "На проверке",
    accepted: "Принято",
    revision_requested: "Доработка",
  }[item.status];
}

function attachmentIcon(kind: AttachmentKind | null): string {
  return {
    document: "DOC",
    photo: "IMG",
    video: "▶",
    video_note: "▶",
    text: "TXT",
  }[kind ?? "text"];
}

function filterTitle(filter: ReviewFilter): string {
  if (filter === "pending") return "Работы на проверку";
  if (filter === "reviewed") return "История проверок";
  return "Все домашние задания";
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

function workCount(count: number): string {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} работа`;
  if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) {
    return `${count} работы`;
  }
  return `${count} работ`;
}

function studentCount(count: number): string {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} ученик`;
  if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)) {
    return `${count} ученика`;
  }
  return `${count} учеников`;
}
