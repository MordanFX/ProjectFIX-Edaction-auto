import { useEffect, useMemo, useState } from "react";

import { APIError, getCuratorReviewStats } from "../api";
import type { CuratorReviewStats, ReviewQueueItem, Staff } from "../types";

interface CuratorCabinetSectionProps {
  staff: Staff;
  queue: ReviewQueueItem[];
  discordQueue: ReviewQueueItem[];
  onSelect: (item: ReviewQueueItem) => void;
}

export function CuratorCabinetSection({
  staff,
  queue,
  discordQueue,
  onSelect,
}: CuratorCabinetSectionProps) {
  const [stats, setStats] = useState<CuratorReviewStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const assigned = useMemo(
    () =>
      [...queue, ...discordQueue]
        .filter((item) => item.assigned_reviewer_id === staff.id && isPending(item))
        .sort((left, right) => left.submitted_at.localeCompare(right.submitted_at)),
    [discordQueue, queue, staff.id],
  );

  useEffect(() => {
    getCuratorReviewStats()
      .then(setStats)
      .catch((caughtError) =>
        setError(messageFromError(caughtError, "Не удалось загрузить статистику")),
      );
  }, []);

  return (
    <>
      <section className="page-heading">
        <div>
          <p className="eyebrow">Личный кабинет</p>
          <h1>Мои проверки</h1>
          <p className="muted">
            Здесь видно, сколько работ проверено и какие работы сейчас закреплены за
            вами.
          </p>
        </div>
      </section>

      {error && <div className="page-error">{error}</div>}

      <section className="metrics-grid curator-metrics">
        <article className="metric-card metric-card--accent">
          <span>Сейчас в работе</span>
          <strong>{stats?.pending_assigned ?? assigned.length}</strong>
          <small>Закреплены за вами</small>
        </article>
        <article className="metric-card">
          <span>Проверено всего</span>
          <strong>{stats?.reviewed_total ?? 0}</strong>
          <small>Все решения куратора</small>
        </article>
        <article className="metric-card">
          <span>Принято / доработка</span>
          <strong>{stats ? `${stats.accepted_total}/${stats.revision_total}` : "0/0"}</strong>
          <small>Итоговые решения</small>
        </article>
      </section>

      <section className="curator-board">
        <header>
          <div>
            <p className="eyebrow">Очередь</p>
            <h2>Мои закреплённые работы</h2>
          </div>
          <span>{assigned.length}</span>
        </header>
        {assigned.length ? (
          <div className="curator-work-list">
            {assigned.map((item) => (
              <button key={item.submission_id} onClick={() => onSelect(item)}>
                <span>{item.source === "discord" ? "Discord" : "Telegram"}</span>
                <strong>{item.student_name}</strong>
                <small>
                  Урок {item.lesson_position}: {item.lesson_title}
                </small>
                <b>{item.attempt_number} попытка</b>
              </button>
            ))}
          </div>
        ) : (
          <div className="curator-empty">
            Сейчас за вами нет закреплённых работ. Откройте очередь ДЗ и возьмите
            работу в проверку.
          </div>
        )}
      </section>
    </>
  );
}

function isPending(item: ReviewQueueItem): boolean {
  return item.status === "submitted" || item.status === "in_review";
}

function messageFromError(error: unknown, fallback: string): string {
  return error instanceof APIError ? error.message : fallback;
}
