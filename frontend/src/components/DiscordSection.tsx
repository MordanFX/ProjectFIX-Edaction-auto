import { useEffect, useMemo, useState } from "react";

import {
  assignDiscordCourse,
  getDiscordLessonDispatches,
  getDiscordQuestions,
  resolveDiscordQuestion,
  revokeDiscordAccess,
} from "../api";
import type {
  CourseOverview,
  DiscordLessonDispatch,
  DiscordMemberOverview,
  DiscordQuestion,
  DiscordWorkspaceOverview,
  ReviewQueueItem,
} from "../types";

type DiscordTab = "submissions" | "questions" | "participants" | "dispatches";
type SubmissionFilter = "pending" | "all" | "accepted" | "revision_requested";
type ParticipantFilter = "all" | DiscordMemberOverview["status"];
interface SubmissionGroup { latest: ReviewQueueItem; attemptCount: number; }
interface StudentSubmissionGroup {
  studentId: string;
  studentName: string;
  member: DiscordMemberOverview | null;
  items: SubmissionGroup[];
  latest: ReviewQueueItem;
}

interface DiscordSectionProps {
  overview: DiscordWorkspaceOverview;
  queue: ReviewQueueItem[];
  courses: CourseOverview[];
  onRefresh: () => Promise<void>;
  onSelect: (item: ReviewQueueItem) => void;
  onOpenCourse: (course: CourseOverview) => void;
}

export function DiscordSection({
  overview,
  queue,
  courses,
  onRefresh,
  onSelect,
  onOpenCourse,
}: DiscordSectionProps) {
  const [tab, setTab] = useState<DiscordTab>("submissions");
  const [assigning, setAssigning] = useState<DiscordMemberOverview | null>(null);
  const [historyMember, setHistoryMember] = useState<DiscordMemberOverview | null>(null);
  const [profileMember, setProfileMember] = useState<DiscordMemberOverview | null>(null);
  const [dispatches, setDispatches] = useState<DiscordLessonDispatch[]>([]);
  const [questions, setQuestions] = useState<DiscordQuestion[]>([]);
  const groupedSubmissions = useMemo(() => groupSubmissions(queue), [queue]);
  const pending = groupedSubmissions.filter((group) => isPending(group.latest));
  const openQuestions = questions.filter((question) => question.status === "open");
  const history = useMemo(
    () => queue.filter((item) => item.student_id === historyMember?.student_id),
    [queue, historyMember],
  );

  async function loadDispatches() {
    setDispatches(await getDiscordLessonDispatches());
  }

  async function loadQuestions() {
    setQuestions(await getDiscordQuestions());
  }

  useEffect(() => {
    void loadDispatches();
    void loadQuestions();
  }, []);

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Discord homework</p>
          <h1>Домашние задания Discord</h1>
          <p className="muted">Приватные ветки учеников и рабочая очередь куратора.</p>
        </div>
      </div>

      <div className="discord-compact-summary">
        <article><span>Ожидают проверки</span><b>{pending.length}</b><small>Новые работы учеников</small></article>
        <article><span>Вопросы</span><b>{openQuestions.length}</b><small>Нужен ответ куратора</small></article>
        <article><span>Discord-ученики</span><b>{overview.participants}</b><small>Участники с приватной веткой</small></article>
        <article><span>Учатся на курсе</span><b>{overview.active_students}</b><small>Назначен действующий курс</small></article>
      </div>

      <div className="discord-tabs" role="tablist">
        <button className={tab === "submissions" ? "active" : ""} onClick={() => setTab("submissions")}>
          Домашние задания <b>{groupedSubmissions.length}</b>
        </button>
        <button className={tab === "questions" ? "active" : ""} onClick={() => { setTab("questions"); void loadQuestions(); }}>
          Вопросы <b>{openQuestions.length}</b>
        </button>
        <button className={tab === "dispatches" ? "active" : ""} onClick={() => { setTab("dispatches"); void loadDispatches(); }}>
          Рассылки <b>{dispatches.length}</b>
        </button>
      </div>

      {tab === "submissions" ? (
        <SubmissionQueue queue={queue} members={overview.members} onSelect={onSelect} />
      ) : tab === "questions" ? (
        <QuestionQueue questions={questions} onRefresh={loadQuestions} />
      ) : tab === "participants" ? (
        <ParticipantList
          members={overview.members}
          onAssign={setAssigning}
          onHistory={setHistoryMember}
          onProfile={setProfileMember}
          onChanged={onRefresh}
          courses={courses}
          onOpenCourse={onOpenCourse}
        />
      ) : (
        <DispatchHistory dispatches={dispatches} onRefresh={loadDispatches} />
      )}

      {assigning && (
        <CourseAssignmentModal
          member={assigning}
          courses={courses}
          onClose={() => setAssigning(null)}
          onSaved={async () => { setAssigning(null); await onRefresh(); }}
        />
      )}
      {historyMember && (
        <HistoryModal
          member={historyMember}
          items={history}
          onClose={() => setHistoryMember(null)}
          onSelect={onSelect}
        />
      )}
      {profileMember && (
        <ParticipantProfileModal
          member={profileMember}
          onClose={() => setProfileMember(null)}
        />
      )}
    </>
  );
}

function DispatchHistory({ dispatches, onRefresh }: {
  dispatches: DiscordLessonDispatch[];
  onRefresh: () => Promise<void>;
}) {
  return <section className="discord-board">
    <header><div><p className="eyebrow">Доставка</p><h2>История рассылок</h2></div><button className="secondary-button" onClick={() => void onRefresh()}>↻ Обновить</button></header>
    {dispatches.length ? <div className="discord-dispatch-history">{dispatches.map((dispatch) => <article key={dispatch.dispatch_id}>
      <div><span>{dispatch.course_title} · урок {dispatch.lesson_position}</span><strong>{dispatch.lesson_title}</strong><small>{formatShortDate(dispatch.created_at)} · {dispatch.created_by}</small></div>
      <div className="discord-delivery-counts"><span><b>{dispatch.sent_count}</b> отправлено</span><span><b>{dispatch.pending_count}</b> ожидает</span><span className={dispatch.failed_count ? "has-errors" : ""}><b>{dispatch.failed_count}</b> ошибок</span></div>
      <span className="discord-recipient-total">{dispatch.recipient_count} получателей</span>
    </article>)}</div> : <div className="discord-empty"><strong>Рассылок пока нет</strong><span>Опубликуй урок и нажми «Выдать ДЗ».</span></div>}
  </section>;
}

function QuestionQueue({ questions, onRefresh }: {
  questions: DiscordQuestion[];
  onRefresh: () => Promise<void>;
}) {
  const [filter, setFilter] = useState<"open" | "all" | "resolved">("open");
  const filtered = questions.filter((question) =>
    filter === "all" ? true : question.status === filter,
  );

  async function resolve(questionId: string) {
    await resolveDiscordQuestion(questionId);
    await onRefresh();
  }

  return <section className="discord-board">
    <header>
      <div><p className="eyebrow">Коммуникация</p><h2>Вопросы от учеников</h2></div>
      <div className="discord-board-actions">
        <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
          <option value="open">Открытые</option>
          <option value="resolved">Закрытые</option>
          <option value="all">Все вопросы</option>
        </select>
        <button className="secondary-button" onClick={() => void onRefresh()}>↻ Обновить</button>
      </div>
    </header>
    {filtered.length ? <div className="discord-question-list">
      {filtered.map((question) => {
        const threadUrl = `https://discord.com/channels/${question.guild_id}/${question.channel_id}`;
        const messageUrl = `${threadUrl}/${question.message_id}`;
        const name = question.discord_display_name || question.student_name || "Discord-ученик";
        return <article key={question.question_id}>
          <div className="discord-question-list__main">
            <span className="discord-submission-list__avatar">{initials(name)}</span>
            <div>
              <strong>{name}</strong>
              <small>{formatShortDate(question.created_at)} · {question.attachment_count ? `${question.attachment_count} файл.` : "текст"}</small>
              <p>{question.text_body || "Сообщение без текста, смотри вложение в Discord."}</p>
              {question.status === "resolved" && <em>Закрыто: {question.resolved_by || "куратор"}{question.resolved_at ? ` · ${formatShortDate(question.resolved_at)}` : ""}</em>}
            </div>
          </div>
          <div className="discord-question-list__actions">
            <b className={`discord-work-status discord-work-status--${question.status}`}>{question.status === "open" ? "Открыт" : "Закрыт"}</b>
            <a href={messageUrl} target="_blank" rel="noreferrer">Открыть сообщение ↗</a>
            <a href={threadUrl} target="_blank" rel="noreferrer">Открыть ветку ↗</a>
            {question.status === "open" && <button onClick={() => void resolve(question.question_id)}>Закрыть вопрос</button>}
          </div>
        </article>;
      })}
    </div> : <div className="discord-empty"><strong>Вопросов нет</strong><span>Когда ученик нажмёт «Уточнить вопрос», обращение появится здесь.</span></div>}
  </section>;
}

function SubmissionQueue({
  queue,
  members,
  onSelect,
}: {
  queue: ReviewQueueItem[];
  members: DiscordMemberOverview[];
  onSelect: (item: ReviewQueueItem) => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<SubmissionFilter>("pending");
  const [course, setCourse] = useState("all");
  const courseNames = [...new Set(queue.map((item) => item.course_title))].sort();
  const groups = useMemo(() => groupSubmissions(queue), [queue]);
  const memberByStudentId = useMemo(() => new Map(
    members.flatMap((member) => member.student_id ? [[member.student_id, member] as const] : []),
  ), [members]);
  const filteredGroups = groups.filter(({ latest: item }) => {
    const needle = search.trim().toLocaleLowerCase("ru");
    const member = memberByStudentId.get(item.student_id);
    const matchesSearch = !needle || [
      item.student_name,
      item.student_username || "",
      item.course_title,
      item.lesson_title,
      item.text_body || "",
      member?.discord_display_name || "",
      member?.discord_username || "",
      member?.discord_global_name || "",
    ].join(" ").toLocaleLowerCase("ru").includes(needle);
    const matchesStatus = status === "all"
      || (status === "pending" ? isPending(item) : item.status === status);
    const matchesCourse = course === "all" || item.course_title === course;
    return matchesSearch && matchesStatus && matchesCourse;
  });
  const filtered = useMemo(
    () => groupByStudent(filteredGroups, memberByStudentId),
    [filteredGroups, memberByStudentId],
  );

  return (
    <section className="discord-board">
      <header><div><p className="eyebrow">Очередь</p><h2>Домашние работы</h2></div><span>{filteredGroups.length} из {groups.length}</span></header>
      <div className="discord-filters">
        <label className="discord-filter-search">
          <span>Поиск</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Ник, имя, курс, урок или текст ответа" />
        </label>
        <label>
          <span>Статус</span>
          <select value={status} onChange={(event) => setStatus(event.target.value as SubmissionFilter)}>
            <option value="pending">Ожидают проверки</option>
            <option value="revision_requested">На доработке</option>
            <option value="accepted">Приняты</option>
            <option value="all">Все работы</option>
          </select>
        </label>
        <label>
          <span>Курс</span>
          <select value={course} onChange={(event) => setCourse(event.target.value)}>
            <option value="all">Все курсы</option>
            {courseNames.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
      </div>
      {filtered.length ? (
        <div className="discord-submission-list">
          {filtered.map((studentGroup) => (
            <article className="discord-student-submission-card" key={studentGroup.studentId}>
              <header>
                <DiscordAvatar member={studentGroup.member} name={studentGroup.studentName} />
                <div>
                  <strong>{displayStudentName(studentGroup)}</strong>
                  <small>{studentGroup.member?.discord_username ? `@${studentGroup.member.discord_username}` : studentGroup.latest.course_title}</small>
                </div>
                <span>{studentGroup.items.length} {studentGroup.items.length === 1 ? "работа" : "работы"}</span>
              </header>
              <div className="discord-student-submission-card__works">
                {studentGroup.items.map(({ latest: item, attemptCount }) => (
                  <button type="button" key={item.submission_id} onClick={() => onSelect(item)}>
                    <div>
                      <span>{item.course_title}</span>
                      <strong>Урок {item.lesson_position}: {item.lesson_title}</strong>
                      <p>{submissionPreview(item)}</p>
                    </div>
                    <footer>
                      <span>{attemptCount === 1 ? "1 попытка" : `${attemptCount} ${attemptWord(attemptCount)}`}</span>
                      <span>{item.attachment_count ? `${item.attachment_count} файл.` : "Текст"}</span>
                      <span>{formatShortDate(item.submitted_at)}</span>
                      <b className={`discord-work-status discord-work-status--${item.status}`}>{statusActionLabel(item.status)}</b>
                    </footer>
                  </button>
                ))}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="discord-empty discord-empty--queue"><strong>Ничего не найдено</strong><span>{groups.length ? "Измени фильтры или поисковый запрос." : "Новые работы из личных веток появятся здесь."}</span></div>
      )}
    </section>
  );
}

function groupSubmissions(queue: ReviewQueueItem[]): SubmissionGroup[] {
  const groups = new Map<string, ReviewQueueItem[]>();
  for (const item of queue) {
    const key = `${item.student_id}\u0000${item.course_title}\u0000${item.lesson_position}\u0000${item.lesson_title}`;
    const attempts = groups.get(key) || [];
    attempts.push(item);
    groups.set(key, attempts);
  }
  return [...groups.values()]
    .map((attempts) => {
      const ordered = [...attempts].sort((left, right) =>
        right.attempt_number - left.attempt_number
        || new Date(right.submitted_at).getTime() - new Date(left.submitted_at).getTime());
      return { latest: ordered[0], attemptCount: ordered.length };
    })
    .sort((left, right) => new Date(right.latest.submitted_at).getTime() - new Date(left.latest.submitted_at).getTime());
}

function groupByStudent(
  groups: SubmissionGroup[],
  memberByStudentId: Map<string, DiscordMemberOverview>,
): StudentSubmissionGroup[] {
  const result = new Map<string, StudentSubmissionGroup>();
  for (const group of groups) {
    const key = group.latest.student_id;
    const existing = result.get(key);
    if (existing) {
      existing.items.push(group);
      if (new Date(group.latest.submitted_at) > new Date(existing.latest.submitted_at)) {
        existing.latest = group.latest;
      }
      continue;
    }
    result.set(key, {
      studentId: key,
      studentName: group.latest.student_name,
      member: memberByStudentId.get(key) || null,
      items: [group],
      latest: group.latest,
    });
  }
  return [...result.values()]
    .map((group) => ({
      ...group,
      items: [...group.items].sort((left, right) =>
        new Date(right.latest.submitted_at).getTime() - new Date(left.latest.submitted_at).getTime()),
    }))
    .sort((left, right) =>
      new Date(right.latest.submitted_at).getTime() - new Date(left.latest.submitted_at).getTime());
}

function DiscordAvatar({ member, name }: { member: DiscordMemberOverview | null; name: string }) {
  return member?.avatar_url
    ? <img className="discord-submission-list__avatar discord-submission-list__avatar--image" src={member.avatar_url} alt="" />
    : <span className="discord-submission-list__avatar">{initials(member?.discord_display_name || name)}</span>;
}

function displayStudentName(group: StudentSubmissionGroup) {
  return group.member?.discord_display_name || group.studentName;
}

function attemptWord(count: number) {
  const lastTwo = count % 100;
  const last = count % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return "попыток";
  if (last === 1) return "попытка";
  if (last >= 2 && last <= 4) return "попытки";
  return "попыток";
}

function submissionPreview(item: ReviewQueueItem) {
  const text = item.text_body?.trim();
  if (!text) return item.attachment_count ? "Ответ приложен файлом. Открой работу, чтобы посмотреть вложения." : "Текстового ответа нет.";
  return text.length > 150 ? `${text.slice(0, 150)}…` : text;
}

function ParticipantList({ members, onAssign, onHistory, onProfile, onChanged, courses, onOpenCourse }: {
  members: DiscordMemberOverview[];
  onAssign: (member: DiscordMemberOverview) => void;
  onHistory: (member: DiscordMemberOverview) => void;
  onProfile: (member: DiscordMemberOverview) => void;
  onChanged: () => Promise<void>;
  courses: CourseOverview[];
  onOpenCourse: (course: CourseOverview) => void;
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ParticipantFilter>("all");
  const [course, setCourse] = useState("all");
  const filtered = members.filter((member) => {
    const needle = search.trim().toLocaleLowerCase("ru");
    const name = member.discord_display_name || member.student_name || "";
    const matchesSearch = !needle || `${name} ${member.discord_username || ""} ${member.course_title || ""}`.toLocaleLowerCase("ru").includes(needle);
    const matchesStatus = status === "all" || member.status === status;
    const matchesCourse = course === "all"
      || (course === "none" ? member.course_id === null : member.course_id === course);
    return matchesSearch && matchesStatus && matchesCourse;
  });

  return (
    <section className="discord-board">
      <header><div><p className="eyebrow">Управление</p><h2>Discord-участники</h2></div><span>{filtered.length} из {members.length}</span></header>
      <div className="discord-filters">
        <label className="discord-filter-search"><span>Поиск</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Имя участника" /></label>
        <label><span>Статус</span><select value={status} onChange={(event) => setStatus(event.target.value as ParticipantFilter)}><option value="all">Все статусы</option><option value="active">Учится</option><option value="completed">Курс завершён</option><option value="no_access">Ожидает курса</option><option value="left">Покинул сервер</option><option value="unregistered">Регистрация</option></select></label>
        <label><span>Курс</span><select value={course} onChange={(event) => setCourse(event.target.value)}><option value="all">Все курсы</option><option value="none">Без курса</option>{courses.map((item) => <option key={item.course_id} value={item.course_id}>{item.title}</option>)}</select></label>
      </div>
      {filtered.length ? <div className="discord-participant-list">
        {filtered.map((member) => {
          const threadUrl = member.channel_id
            ? `https://discord.com/channels/${member.guild_id}/${member.channel_id}`
            : null;
          const assignedCourse = courses.find((course) => course.course_id === member.course_id);
          return <article key={`${member.guild_id}-${member.discord_user_id}`}>
            <img src={member.avatar_url || ""} alt="" />
            <div className="discord-participant-list__identity">
              <strong>{member.discord_display_name || member.student_name || "Discord-участник"}</strong>
              <small>{member.discord_username ? `@${member.discord_username}` : "Discord-профиль"}</small>
              <span>{member.course_title ? `${member.course_title} · урок ${member.current_lesson_position || 1} из ${member.total_lessons}` : "Курс ещё не назначен"}</span>
            </div>
            <span className={`discord-status discord-status--${member.status}`}>{memberStatusLabel(member.status)}</span>
            <div className="discord-participant-list__stats"><b>{member.pending_submissions}</b><small>на проверке</small><span>{member.total_submissions} всего</span></div>
            <div className="discord-participant-list__activity"><small>Активность</small><strong>{formatRelativeDate(member.last_activity_at)}</strong></div>
            <div className="discord-participant-list__actions">
              <button onClick={() => onProfile(member)}>Профиль</button>
              {threadUrl && <a href={threadUrl} target="_blank" rel="noreferrer">Открыть ветку</a>}
              <button onClick={() => onHistory(member)}>История</button>
              {assignedCourse && <button onClick={() => onOpenCourse(assignedCourse)}>Настроить ДЗ</button>}
              <button className="primary" onClick={() => onAssign(member)}>{member.status === "active" ? "Сменить курс" : "Назначить курс"}</button>
              {member.status === "active" && member.student_id && <button className="danger" onClick={async () => { await revokeDiscordAccess(member.student_id!); await onChanged(); }}>Закрыть доступ</button>}
            </div>
          </article>;
        })}
      </div> : <div className="discord-empty"><strong>Ничего не найдено</strong><span>{members.length ? "Измени фильтры или поисковый запрос." : <>После команды <code>/homework</code> пользователь появится здесь.</>}</span></div>}
    </section>
  );
}

function CourseAssignmentModal({ member, courses, onClose, onSaved }: {
  member: DiscordMemberOverview;
  courses: CourseOverview[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [courseId, setCourseId] = useState(member.course_id || courses[0]?.course_id || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    if (!member.student_id || !courseId) return;
    setBusy(true); setError(null);
    try { await assignDiscordCourse(member.student_id, courseId); await onSaved(); }
    catch { setError("Не удалось назначить курс"); setBusy(false); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="discord-action-modal">
      <button className="modal-close" onClick={onClose}>×</button>
      <header className="discord-action-modal__header"><span className="discord-submission-list__avatar">{initials(member.discord_display_name || member.student_name || "D")}</span><div><h2>Курс участника</h2><p>{member.discord_display_name || member.student_name}</p></div></header>
      {courses.length ? <label className="discord-modal-field"><span>Discord-курс</span><select value={courseId} onChange={(event) => setCourseId(event.target.value)}>{courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.title} · {course.lessons_count} уроков</option>)}</select></label> : <div className="form-error">Сначала создайте курс типа Discord.</div>}
      {error && <div className="form-error">{error}</div>}
      <div className="discord-modal-actions"><button type="button" onClick={onClose}>Отмена</button><button className="course-save-button" disabled={!courseId || busy} onClick={() => void save()}>{busy ? "Сохраняем…" : member.course_id ? "Сменить курс" : "Назначить курс"}</button></div>
    </section>
  </div>;
}

function HistoryModal({ member, items, onClose, onSelect }: { member: DiscordMemberOverview; items: ReviewQueueItem[]; onClose: () => void; onSelect: (item: ReviewQueueItem) => void }) {
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="discord-action-modal discord-history-modal">
      <button className="modal-close" onClick={onClose}>×</button>
      <header className="discord-action-modal__header"><span className="discord-submission-list__avatar">{initials(member.discord_display_name || member.student_name || "D")}</span><div><h2>История работ</h2><p>{member.discord_display_name || member.student_name}</p></div></header>
      {items.length ? <div>{items.map((item) => <button key={item.submission_id} onClick={() => onSelect(item)}><span><strong>{item.lesson_title}</strong><small>Урок {item.lesson_position} · попытка {item.attempt_number} · {formatShortDate(item.submitted_at)}</small></span><b className={`discord-work-status discord-work-status--${item.status}`}>{statusLabel(item.status)}</b></button>)}</div> : <div className="discord-modal-empty">Участник ещё не отправлял работы.</div>}
    </section>
  </div>;
}

function ParticipantProfileModal({ member, onClose }: { member: DiscordMemberOverview; onClose: () => void }) {
  const threadUrl = member.channel_id
    ? `https://discord.com/channels/${member.guild_id}/${member.channel_id}`
    : null;
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="discord-action-modal discord-profile-modal">
      <button className="modal-close" onClick={onClose}>×</button>
      <header className="discord-profile-modal__hero">
        <img src={member.avatar_url || ""} alt="" />
        <div><span className={`discord-status discord-status--${member.status}`}>{memberStatusLabel(member.status)}</span><h2>{member.discord_display_name || member.student_name}</h2><p>{member.discord_username ? `@${member.discord_username}` : "Username пока не получен"}</p></div>
      </header>
      <section className="discord-profile-section">
        <h3>Discord-профиль</h3>
        <div className="discord-profile-facts">
          <ProfileFact label="Discord ID" value={member.discord_user_id} mono />
          <ProfileFact label="На сервере с" value={formatDateValue(member.guild_joined_at)} />
          <ProfileFact label="Первый /homework" value={formatDateValue(member.registered_at)} />
          <ProfileFact label="Последняя активность" value={formatDateValue(member.last_activity_at)} />
        </div>
      </section>
      <section className="discord-profile-section">
        <h3>Обучение</h3>
        <div className="discord-profile-facts">
          <ProfileFact label="Курс" value={member.course_title || "Не назначен"} />
          <ProfileFact label="Поток" value={member.cohort_title || "—"} />
          <ProfileFact label="Текущий урок" value={member.course_title ? `${member.current_lesson_position || 1} из ${member.total_lessons}` : "—"} />
          <ProfileFact label="Домашние работы" value={`${member.total_submissions} · ${member.pending_submissions} на проверке`} />
        </div>
      </section>
      <section className="discord-profile-section discord-profile-thread">
        <div><h3>Личная ветка</h3><p>{member.thread_name || "Название обновится после следующего /homework"}</p></div>
        {threadUrl && <a href={threadUrl} target="_blank" rel="noreferrer">Открыть в Discord ↗</a>}
      </section>
    </section>
  </div>;
}

function ProfileFact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><span>{label}</span><strong className={mono ? "mono" : ""}>{value}</strong></div>;
}

function isPending(item: ReviewQueueItem) { return item.status === "submitted" || item.status === "in_review"; }
function statusLabel(status: ReviewQueueItem["status"]) { return { submitted: "Ожидает", in_review: "На проверке", accepted: "Принято", revision_requested: "Доработка" }[status]; }
function statusActionLabel(status: ReviewQueueItem["status"]) { return { submitted: "Проверить", in_review: "Проверить", accepted: "Открыть итог", revision_requested: "Смотреть доработку" }[status]; }
function memberStatusLabel(status: DiscordMemberOverview["status"]) { return { active: "Учится", completed: "Курс завершён", unregistered: "Регистрация", no_access: "Ожидает курса", left: "Покинул сервер" }[status]; }
function initials(name: string) { return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join(""); }
function formatShortDate(value: string) { return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function formatDateValue(value: string | null) { return value ? new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "Нет данных"; }
function formatRelativeDate(value: string | null) { if (!value) return "Нет данных"; const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000)); if (minutes < 1) return "сейчас"; if (minutes < 60) return `${minutes} мин. назад`; const hours = Math.floor(minutes / 60); if (hours < 24) return `${hours} ч. назад`; return formatShortDate(value); }
