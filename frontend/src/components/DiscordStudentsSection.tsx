import { useMemo, useState } from "react";

import { assignDiscordCourse, revokeDiscordAccess } from "../api";
import type { CourseOverview, DiscordMemberOverview, DiscordWorkspaceOverview, ReviewQueueItem } from "../types";

type ParticipantFilter = "all" | DiscordMemberOverview["status"];

interface DiscordStudentsSectionProps {
  overview: DiscordWorkspaceOverview;
  courses: CourseOverview[];
  submissions: ReviewQueueItem[];
  onChanged: () => Promise<void>;
  onSelectSubmission: (item: ReviewQueueItem) => void;
}

export function DiscordStudentsSection({ overview, courses, submissions, onChanged, onSelectSubmission }: DiscordStudentsSectionProps) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ParticipantFilter>("all");
  const [courseId, setCourseId] = useState("all");
  const [assigning, setAssigning] = useState<DiscordMemberOverview | null>(null);
  const [profile, setProfile] = useState<DiscordMemberOverview | null>(null);
  const [history, setHistory] = useState<DiscordMemberOverview | null>(null);

  const filtered = useMemo(() => overview.members.filter((member) => {
    const needle = search.trim().toLocaleLowerCase("ru");
    const haystack = [member.discord_display_name, member.discord_username, member.student_name, member.thread_name, member.course_title].filter(Boolean).join(" ").toLocaleLowerCase("ru");
    return (!needle || haystack.includes(needle))
      && (status === "all" || member.status === status)
      && (courseId === "all" || (courseId === "none" ? member.course_id === null : member.course_id === courseId));
  }), [courseId, overview.members, search, status]);

  const withoutCourse = overview.members.filter((member) => !member.course_id).length;
  const memberHistory = submissions.filter((item) => item.student_id === history?.student_id);

  return <>
    <div className="page-heading">
      <div><p className="eyebrow">Discord · участники</p><h1>Discord-ученики</h1><p className="muted">Курсы, прогресс, работы и приватные ветки в одном месте.</p></div>
    </div>

    <div className="discord-compact-summary">
      <article><span>Всего учеников</span><b>{overview.participants}</b><small>Создали приватную ветку</small></article>
      <article><span>Учатся на курсе</span><b>{overview.active_students}</b><small>Назначен действующий курс</small></article>
      <article><span>Без курса</span><b>{withoutCourse}</b><small>Нужно назначить обучение</small></article>
    </div>

    <section className="discord-board discord-students-board">
      <header><div><p className="eyebrow">Управление</p><h2>Список учеников</h2></div><span>{filtered.length} из {overview.members.length}</span></header>
      <div className="discord-filters">
        <label className="discord-filter-search"><span>Поиск</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Имя, Discord или название ветки" /></label>
        <label><span>Статус</span><select value={status} onChange={(event) => setStatus(event.target.value as ParticipantFilter)}><option value="all">Все статусы</option><option value="active">Учится</option><option value="completed">Курс завершён</option><option value="no_access">Ожидает курса</option><option value="left">Покинул сервер</option><option value="unregistered">Регистрация</option></select></label>
        <label><span>Курс</span><select value={courseId} onChange={(event) => setCourseId(event.target.value)}><option value="all">Все курсы</option><option value="none">Без курса</option>{courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.title}</option>)}</select></label>
      </div>

      {filtered.length ? <div className="discord-participant-list">
        {filtered.map((member) => {
          const threadUrl = member.channel_id ? `https://discord.com/channels/${member.guild_id}/${member.channel_id}` : null;
          return <article key={`${member.guild_id}-${member.discord_user_id}`}>
            {member.avatar_url ? <img src={member.avatar_url} alt="" /> : <span className="discord-participant-avatar">{initials(displayName(member))}</span>}
            <div className="discord-participant-list__identity">
              <strong>{displayName(member)}</strong>
              <small>{member.discord_username ? `@${member.discord_username}` : `Discord ID: ${member.discord_user_id}`}</small>
              <div className="discord-participant-list__course">
                <span>{member.course_title || "Курс ещё не назначен"}</span>
                {member.course_title && <b>Текущий урок: {member.current_lesson_position || 1} из {member.total_lessons}</b>}
              </div>
            </div>
            <span className={`discord-status discord-status--${member.status}`}>{memberStatusLabel(member.status)}</span>
            <div className="discord-participant-list__stats"><b>{member.pending_submissions}</b><small>на проверке</small><span>{member.total_submissions} всего</span></div>
            <div className="discord-participant-list__activity"><small>Последняя активность</small><strong>{formatRelativeDate(member.last_activity_at)}</strong></div>
            <div className="discord-participant-list__actions">
              <div className="discord-participant-list__primary-actions">
                <button className="primary" onClick={() => setHistory(member)}>Работы <span>{member.total_submissions}</span></button>
                <button className="primary" onClick={() => setAssigning(member)}>{member.course_id ? "Изменить курс" : "Назначить курс"}</button>
              </div>
              <div className="discord-participant-list__secondary-actions">
                <button onClick={() => setProfile(member)}>Карточка ученика</button>
                {threadUrl && <a href={threadUrl} target="_blank" rel="noreferrer">Открыть ветку ↗</a>}
              </div>
            </div>
          </article>;
        })}
      </div> : <div className="discord-empty"><strong>Ученики не найдены</strong><span>{overview.members.length ? "Измените фильтры или поисковый запрос." : <>После команды <code>/homework</code> участник появится здесь.</>}</span></div>}
    </section>

    {assigning && <CourseAssignmentModal member={assigning} courses={courses} onClose={() => setAssigning(null)} onSaved={async () => { setAssigning(null); await onChanged(); }} />}
    {profile && <ParticipantProfileModal member={profile} onClose={() => setProfile(null)} onAccessRevoked={async () => { setProfile(null); await onChanged(); }} />}
    {history && <HistoryModal member={history} items={memberHistory} onClose={() => setHistory(null)} onSelect={(item) => { setHistory(null); onSelectSubmission(item); }} />}
  </>;
}

function CourseAssignmentModal({ member, courses, onClose, onSaved }: { member: DiscordMemberOverview; courses: CourseOverview[]; onClose: () => void; onSaved: () => Promise<void> }) {
  const [courseId, setCourseId] = useState(member.course_id || courses[0]?.course_id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    if (!member.student_id || !courseId) return;
    setBusy(true); setError(null);
    try { await assignDiscordCourse(member.student_id, courseId); await onSaved(); }
    catch { setError("Не удалось назначить курс"); setBusy(false); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="discord-action-modal"><button className="modal-close" onClick={onClose}>×</button><header className="discord-action-modal__header"><span className="discord-submission-list__avatar">{initials(displayName(member))}</span><div><h2>{member.course_id ? "Сменить курс" : "Назначить курс"}</h2><p>{displayName(member)}</p></div></header>{courses.length ? <label className="discord-modal-field"><span>Discord-курс</span><select value={courseId} onChange={(event) => setCourseId(event.target.value)}>{courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.title} · {course.lessons_count} уроков</option>)}</select></label> : <div className="form-error">Сначала создайте Discord-курс.</div>}{error && <div className="form-error">{error}</div>}<div className="discord-modal-actions"><button type="button" onClick={onClose}>Отмена</button><button className="course-save-button" disabled={!courseId || busy} onClick={() => void save()}>{busy ? "Сохраняем…" : "Сохранить"}</button></div></section></div>;
}

function HistoryModal({ member, items, onClose, onSelect }: { member: DiscordMemberOverview; items: ReviewQueueItem[]; onClose: () => void; onSelect: (item: ReviewQueueItem) => void }) {
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="discord-action-modal discord-history-modal"><button className="modal-close" onClick={onClose}>×</button><header className="discord-action-modal__header"><span className="discord-submission-list__avatar">{initials(displayName(member))}</span><div><h2>История работ</h2><p>{displayName(member)}</p></div></header>{items.length ? <div>{items.map((item) => <button key={item.submission_id} onClick={() => onSelect(item)}><span><strong>{item.lesson_title}</strong><small>{item.course_title} · урок {item.lesson_position} · попытка {item.attempt_number} · {formatShortDate(item.submitted_at)}</small></span><b className={`discord-work-status discord-work-status--${item.status}`}>{submissionStatusLabel(item.status)}</b></button>)}</div> : <div className="discord-modal-empty">Ученик ещё не отправлял работы.</div>}</section></div>;
}

function ParticipantProfileModal({ member, onClose, onAccessRevoked }: { member: DiscordMemberOverview; onClose: () => void; onAccessRevoked: () => Promise<void> }) {
  const threadUrl = member.channel_id ? `https://discord.com/channels/${member.guild_id}/${member.channel_id}` : null;
  const [busy, setBusy] = useState(false);
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><section className="discord-action-modal discord-profile-modal"><button className="modal-close" onClick={onClose}>×</button><header className="discord-profile-modal__hero">{member.avatar_url ? <img src={member.avatar_url} alt="" /> : <span className="discord-profile-avatar">{initials(displayName(member))}</span>}<div><span className={`discord-status discord-status--${member.status}`}>{memberStatusLabel(member.status)}</span><h2>{displayName(member)}</h2><p>{member.discord_username ? `@${member.discord_username}` : "Username не получен"}</p></div></header><section className="discord-profile-section"><h3>Обучение</h3><div className="discord-profile-facts"><ProfileFact label="Курс" value={member.course_title || "Не назначен"} /><ProfileFact label="Текущий урок" value={member.course_title ? `${member.current_lesson_position || 1} из ${member.total_lessons}` : "—"} /><ProfileFact label="Работы" value={`${member.total_submissions} · ${member.pending_submissions} на проверке`} /><ProfileFact label="Активность" value={formatDateValue(member.last_activity_at)} /></div></section><section className="discord-profile-section"><h3>Discord</h3><div className="discord-profile-facts"><ProfileFact label="Discord ID" value={member.discord_user_id} mono /><ProfileFact label="На сервере с" value={formatDateValue(member.guild_joined_at)} /><ProfileFact label="Первая команда /homework" value={formatDateValue(member.registered_at)} /><ProfileFact label="Приватная ветка" value={member.thread_name || "Не создана"} /></div></section><section className="discord-profile-section discord-profile-thread"><div><h3>Действия</h3><p>Переход в ветку или закрытие доступа к курсу.</p></div><div className="discord-profile-actions">{threadUrl && <a href={threadUrl} target="_blank" rel="noreferrer">Открыть ветку ↗</a>}{member.status === "active" && member.student_id && <button disabled={busy} onClick={async () => { setBusy(true); await revokeDiscordAccess(member.student_id!); await onAccessRevoked(); }}>Закрыть доступ</button>}</div></section></section></div>;
}

function ProfileFact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) { return <div><span>{label}</span><strong className={mono ? "mono" : ""}>{value}</strong></div>; }
function displayName(member: DiscordMemberOverview) { return member.discord_display_name || member.student_name || "Discord-участник"; }
function initials(name: string) { return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() || "").join(""); }
function memberStatusLabel(status: DiscordMemberOverview["status"]) { return { active: "Учится", completed: "Курс завершён", unregistered: "Регистрация", no_access: "Ожидает курса", left: "Покинул сервер" }[status]; }
function submissionStatusLabel(status: ReviewQueueItem["status"]) { return { submitted: "Ожидает", in_review: "На проверке", accepted: "Принято", revision_requested: "Доработка" }[status]; }
function formatShortDate(value: string) { return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function formatDateValue(value: string | null) { return value ? new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "Нет данных"; }
function formatRelativeDate(value: string | null) { if (!value) return "Нет данных"; const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000)); if (minutes < 1) return "сейчас"; if (minutes < 60) return `${minutes} мин. назад`; const hours = Math.floor(minutes / 60); if (hours < 24) return `${hours} ч. назад`; return formatShortDate(value); }
