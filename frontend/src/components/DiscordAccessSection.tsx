import { useEffect, useMemo, useState } from "react";

import {
  closeDiscordAccess,
  extendDiscordAccess,
  getDiscordAccesses,
  setDiscordAccessExpiry,
} from "../api";
import type { DiscordAccess, DiscordAccessStatus } from "../types";

type AccessFilter = "all" | DiscordAccessStatus;

export function DiscordAccessSection() {
  const [items, setItems] = useState<DiscordAccess[]>([]);
  const [filter, setFilter] = useState<AccessFilter>("all");
  const [search, setSearch] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [customDates, setCustomDates] = useState<Record<string, string>>({});

  async function load() {
    setItems(await getDiscordAccesses());
  }

  useEffect(() => {
    void load().catch(() => setError("Не удалось загрузить доступы"));
  }, []);

  const stats = useMemo(() => {
    const active = items.filter((item) => item.status === "active" || item.status === "no_expiry");
    const expiring = items.filter((item) => item.status === "expiring");
    const expired = items.filter((item) => item.status === "expired" || item.status === "revoked");
    return { active: active.length, expiring: expiring.length, expired: expired.length };
  }, [items]);

  const filtered = items.filter((item) => {
    const needle = search.trim().toLocaleLowerCase("ru");
    const matchesSearch = !needle
      || `${item.discord_display_name} ${item.discord_username || ""} ${item.course_title || ""}`
        .toLocaleLowerCase("ru")
        .includes(needle);
    const matchesStatus = filter === "all" || item.status === filter;
    return matchesSearch && matchesStatus;
  });

  async function extend(studentId: string, months: 1 | 3) {
    setBusyId(studentId);
    setError(null);
    try {
      await extendDiscordAccess(studentId, months);
      await load();
    } catch {
      setError("Не удалось продлить доступ. Проверь, что ученику назначен Discord-курс.");
    } finally {
      setBusyId(null);
    }
  }

  async function close(studentId: string) {
    setBusyId(studentId);
    setError(null);
    try {
      await closeDiscordAccess(studentId);
      await load();
    } catch {
      setError("Не удалось закрыть доступ.");
    } finally {
      setBusyId(null);
    }
  }

  async function setExpiry(studentId: string) {
    const value = customDates[studentId];
    if (!value) {
      setError("Выбери дату окончания доступа.");
      return;
    }
    setBusyId(studentId);
    setError(null);
    try {
      await setDiscordAccessExpiry(studentId, endOfDayIso(value));
      await load();
    } catch {
      setError("Не удалось установить дату доступа.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Discord access</p>
          <h1>Доступы и подписки</h1>
          <p className="muted">Базовый ручной контроль срока доступа до подключения CRM.</p>
        </div>
      </div>

      <div className="discord-compact-summary discord-compact-summary--access">
        <article><span>Активных</span><b>{stats.active}</b><small>Есть доступ или без срока</small></article>
        <article><span>Скоро истекают</span><b>{stats.expiring}</b><small>7 дней или меньше</small></article>
        <article><span>Истёк / закрыт</span><b>{stats.expired}</b><small>Нужно продлить или проверить</small></article>
      </div>

      <section className="discord-board">
        <header>
          <div><p className="eyebrow">Управление</p><h2>Discord-доступы</h2></div>
          <button className="secondary-button" onClick={() => void load()}>↻ Обновить</button>
        </header>
        {error && <div className="form-error">{error}</div>}
        <div className="discord-filters">
          <label className="discord-filter-search">
            <span>Поиск</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Имя, username или курс" />
          </label>
          <label>
            <span>Статус</span>
            <select value={filter} onChange={(event) => setFilter(event.target.value as AccessFilter)}>
              <option value="all">Все статусы</option>
              <option value="active">Активен</option>
              <option value="no_expiry">Без срока</option>
              <option value="expiring">Скоро истекает</option>
              <option value="expired">Истёк</option>
              <option value="revoked">Закрыт</option>
              <option value="no_course">Без курса</option>
            </select>
          </label>
        </div>

        {filtered.length ? (
          <div className="discord-access-list">
            {filtered.map((item) => {
              const threadUrl = item.channel_id
                ? `https://discord.com/channels/${item.guild_id}/${item.channel_id}`
                : null;
              return (
                <article key={item.student_id}>
                  <img src={item.avatar_url || ""} alt="" />
                  <div className="discord-access-list__identity">
                    <strong>{item.discord_display_name}</strong>
                    <small>{item.discord_username ? `@${item.discord_username}` : `ID ${item.discord_user_id}`}</small>
                    <span>{item.course_title || "Курс не назначен"}</span>
                  </div>
                  <div className="discord-access-list__dates">
                    <span>Купил доступ</span>
                    <strong>{formatDate(item.access_started_at) || "Не указано"}</strong>
                    <small>{sourceLabel(item.access_source, item.access_plan)}</small>
                  </div>
                  <div className="discord-access-list__dates">
                    <span>Доступ до</span>
                    <strong>{formatDate(item.access_expires_at) || "Без срока"}</strong>
                    <small>{daysLeftLabel(item)}</small>
                  </div>
                  <b className={`discord-access-status discord-access-status--${item.status}`}>
                    {statusLabel(item.status)}
                  </b>
                  <div className="discord-access-list__actions">
                    <button disabled={busyId === item.student_id || item.status === "no_course"} onClick={() => void extend(item.student_id, 1)}>+ 1 месяц</button>
                    <button disabled={busyId === item.student_id || item.status === "no_course"} onClick={() => void extend(item.student_id, 3)}>+ 3 месяца</button>
                    <label className="discord-access-custom-date">
                      <span>до</span>
                      <input
                        type="date"
                        value={customDates[item.student_id] || dateInputValue(item.access_expires_at)}
                        disabled={busyId === item.student_id || item.status === "no_course"}
                        onChange={(event) => setCustomDates((current) => ({
                          ...current,
                          [item.student_id]: event.target.value,
                        }))}
                      />
                    </label>
                    <button disabled={busyId === item.student_id || item.status === "no_course"} onClick={() => void setExpiry(item.student_id)}>Установить</button>
                    <button className="danger" disabled={busyId === item.student_id || item.status === "no_course"} onClick={() => void close(item.student_id)}>Закрыть</button>
                    {threadUrl && <a href={threadUrl} target="_blank" rel="noreferrer">Ветка ↗</a>}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="discord-empty">
            <strong>Доступов пока нет</strong>
            <span>После команды /homework Discord-ученики появятся здесь.</span>
          </div>
        )}
      </section>
    </>
  );
}

function statusLabel(status: DiscordAccessStatus) {
  return {
    active: "Активен",
    expiring: "Истекает",
    expired: "Истёк",
    revoked: "Закрыт",
    no_course: "Без курса",
    no_expiry: "Без срока",
  }[status];
}

function daysLeftLabel(item: DiscordAccess) {
  if (item.status === "no_course") return "Сначала назначь курс";
  if (item.days_left === null) return "Ограничение не задано";
  if (item.status === "expired") return "Срок закончился";
  return `${item.days_left} ${dayWord(item.days_left)} осталось`;
}

function sourceLabel(source: string | null, plan: string | null) {
  const sourceText = source === "manual" || !source ? "Вручную" : source.toUpperCase();
  if (plan === "1_month") return `${sourceText} · 1 месяц`;
  if (plan === "3_month") return `${sourceText} · 3 месяца`;
  if (plan === "custom") return `${sourceText} · своя дата`;
  return sourceText;
}

function dayWord(count: number) {
  const lastTwo = count % 100;
  const last = count % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return "дней";
  if (last === 1) return "день";
  if (last >= 2 && last <= 4) return "дня";
  return "дней";
}

function formatDate(value: string | null) {
  if (!value) return null;
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function dateInputValue(value: string | null) {
  if (!value) return "";
  return new Date(value).toISOString().slice(0, 10);
}

function endOfDayIso(value: string) {
  return `${value}T23:59:59.000Z`;
}
