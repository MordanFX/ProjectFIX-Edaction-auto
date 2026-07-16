import { useEffect, useMemo, useState } from "react";

import {
  APIError,
  assignDiscordCourse,
  createDiscordInvite,
  createDiscordLessonDispatch,
  getCourse,
  getDiscordInvites,
} from "../api";
import type {
  CourseContent,
  CourseOverview,
  DiscordInvite,
  DiscordInviteCreated,
  DiscordLessonDispatch,
  DiscordMemberOverview,
  LessonContent,
  ReviewQueueItem,
} from "../types";

interface DiscordDispatchSectionProps {
  courses: CourseOverview[];
  members: DiscordMemberOverview[];
  submissions: ReviewQueueItem[];
  initialRequest: { courseId: string; lessonId?: string } | null;
  onRequestHandled: () => void;
  onChanged: () => Promise<void>;
  onSelectSubmission: (item: ReviewQueueItem) => void;
}

function inviteStatusLabel(status: string) {
  if (status === "used") return "активирован";
  if (status === "expired") return "истёк";
  return "ждёт активации";
}

function formatInviteDate(value: string) {
  return new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function DiscordDispatchSection({
  courses,
  members,
  submissions,
  initialRequest,
  onRequestHandled,
  onChanged,
  onSelectSubmission,
}: DiscordDispatchSectionProps) {
  const [courseId, setCourseId] = useState(initialRequest?.courseId || courses[0]?.course_id || "");
  const [course, setCourse] = useState<CourseContent | null>(null);
  const [lessonId, setLessonId] = useState(initialRequest?.lessonId || "");
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [invite, setInvite] = useState<DiscordInviteCreated | null>(null);
  const [invites, setInvites] = useState<DiscordInvite[]>([]);
  const [inviteHistoryOpen, setInviteHistoryOpen] = useState(false);
  const [inviteCopied, setInviteCopied] = useState(false);
  const [result, setResult] = useState<DiscordLessonDispatch | null>(null);

  useEffect(() => {
    let active = true;
    getDiscordInvites()
      .then((items) => { if (active) setInvites(items); })
      .catch(() => { /* invite history is non-critical */ });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!initialRequest) return;
    setCourseId(initialRequest.courseId);
    setLessonId(initialRequest.lessonId || "");
    setResult(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
    onRequestHandled();
  }, [initialRequest, onRequestHandled]);

  useEffect(() => {
    if (!courseId) {
      setCourse(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    getCourse(courseId)
      .then((value) => {
        if (!active) return;
        const lessons = dispatchableLessons(value);
        setCourse(value);
        setLessonId((current) => lessons.some((lesson) => lesson.lesson_id === current)
          ? current
          : lessons[0]?.lesson_id || "");
        setSelected([]);
      })
      .catch((caught) => active && setError(errorMessage(caught, "Не удалось загрузить курс")))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [courseId]);

  const lessons = course ? dispatchableLessons(course) : [];
  const lesson = lessons.find((item) => item.lesson_id === lessonId) || null;

  const readyMembers = useMemo(() => members.filter((member) =>
    member.student_id
    && member.channel_id
    && member.status === "active"
    && member.course_id === courseId
    && member.current_lesson_position === lesson?.position,
  ), [members, courseId, lesson?.position]);

  const newCourseMembers = useMemo(() => {
    if (lesson?.position !== 1) return [];
    return members.filter((member) =>
      member.student_id
      && member.channel_id
      && member.is_guild_member
      && !(member.status === "active" && member.course_id === courseId),
    );
  }, [members, courseId, lesson?.position]);

  const blockedMembers = useMemo(() => members.filter((member) =>
    member.student_id
    && member.channel_id
    && member.status === "active"
    && member.course_id === courseId
    && member.current_lesson_position !== lesson?.position,
  ), [members, courseId, lesson?.position]);

  const notReachedMembers = useMemo(() => blockedMembers.filter((member) =>
    lesson?.position
    && (!member.current_lesson_position || member.current_lesson_position < lesson.position),
  ), [blockedMembers, lesson?.position]);

  const passedMembers = useMemo(() => blockedMembers.filter((member) =>
    lesson?.position
    && member.current_lesson_position
    && member.current_lesson_position > lesson.position,
  ), [blockedMembers, lesson?.position]);

  const lessonSubmissions = useMemo(() => lesson && course
    ? submissions.filter((item) => item.course_title === course.title && item.lesson_position === lesson.position)
    : [], [course, lesson, submissions]);

  // Live codes stay in sight — they can still be forwarded to a student.
  // Everything else is history and hides behind a fold.
  const pendingInvites = useMemo(() => invites.filter((item) => item.status === "active"), [invites]);
  const historyInvites = useMemo(() => invites.filter((item) => item.status !== "active"), [invites]);

  const inviteMeta = (item: DiscordInvite) => {
    if (item.status === "used") {
      const member = members.find((candidate) => candidate.discord_user_id === item.used_by_discord_user_id);
      const name = member?.discord_display_name || member?.student_name;
      const when = item.used_at ? formatInviteDate(item.used_at) : null;
      return [name || "ученик", when].filter(Boolean).join(" · ");
    }
    if (item.status === "expired") return `истёк ${formatInviteDate(item.expires_at)}`;
    return `действует до ${formatInviteDate(item.expires_at)}`;
  };

  const selectableMembers = [...readyMembers, ...newCourseMembers];
  const selectableIds = selectableMembers.flatMap((member) => member.student_id ? [member.student_id] : []);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.includes(id));

  function toggle(studentId: string) {
    setSelected((current) => current.includes(studentId)
      ? current.filter((item) => item !== studentId)
      : [...current, studentId]);
  }

  async function send() {
    if (!lesson || !selected.length) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const needsCourse = newCourseMembers
        .flatMap((member) => member.student_id ? [member.student_id] : [])
        .filter((studentId) => selected.includes(studentId));
      for (const studentId of needsCourse) {
        await assignDiscordCourse(studentId, courseId);
      }
      const dispatch = await createDiscordLessonDispatch({
        lesson_id: lesson.lesson_id,
        student_ids: selected,
        custom_message: null,
      });
      setResult(dispatch);
      setSelected([]);
      await onChanged();
    } catch (caught) {
      setError(dispatchError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function generateInvite() {
    if (!courseId) return;
    setInviteBusy(true);
    setInviteError(null);
    setInviteCopied(false);
    try {
      const created = await createDiscordInvite({
        course_id: courseId,
        max_age_seconds: 86400,
      });
      setInvite(created);
      setInvites((current) => [created, ...current]);
    } catch (caught) {
      setInviteError(errorMessage(caught, "Не удалось создать invite-ссылку"));
    } finally {
      setInviteBusy(false);
    }
  }

  async function copyInvite() {
    if (!invite) return;
    // The code is shown once, so hand the curator the whole message to forward
    // rather than two fragments they have to assemble themselves.
    const message = [
      `Заходи на сервер: ${invite.invite_url}`,
      "",
      `Твой код доступа: ${invite.access_code}`,
      "",
      `После входа нажми кнопку «Получить доступ» и введи этот код —`,
      `бот создаст твоё личное пространство для домашних работ.`,
    ].join("\n");
    await navigator.clipboard.writeText(message);
    setInviteCopied(true);
  }

  return <div className="discord-send-page">
    <header className="discord-send-page__heading">
      <div><p className="eyebrow">Discord · выдача заданий</p><h1>Выдать домашнее задание</h1><p>Выберите урок и учеников. Бот отправит задание в каждую приватную ветку.</p></div>
    </header>

    {result && <section className="discord-send-result">
      <div><strong>Задание поставлено в очередь</strong><span>Бот доставит его в приватные ветки. Фактический результат появится в разделе «Рассылки».</span></div>
      <dl><div><dt>{result.recipient_count}</dt><dd>получателей</dd></div><div><dt>{result.pending_count}</dt><dd>ожидают отправки</dd></div><div className={result.failed_count ? "has-errors" : ""}><dt>{result.failed_count}</dt><dd>ошибок</dd></div></dl>
    </section>}
    {error && <div className="form-error">{error}</div>}

    <section className="discord-send-card">
      <header><b>1</b><div><h2>Что отправить</h2><p>Только опубликованные уроки с домашним заданием</p></div></header>
      <div className="discord-send-selects">
        <label><span>Курс</span><select value={courseId} onChange={(event) => { setCourseId(event.target.value); setResult(null); }}>{courses.length ? courses.map((item) => <option key={item.course_id} value={item.course_id}>{item.title}</option>) : <option value="">Нет Discord-курсов</option>}</select></label>
        <label><span>Урок</span><select value={lessonId} disabled={loading || !lessons.length} onChange={(event) => { setLessonId(event.target.value); setSelected([]); setResult(null); }}>{lessons.length ? lessons.map((item) => <option key={item.lesson_id} value={item.lesson_id}>Урок {item.position} · {item.title}</option>) : <option value="">Нет опубликованных уроков с ДЗ</option>}</select></label>
      </div>
    </section>

    <section className="discord-send-card">
      <header><b>2</b><div><h2>Кому отправить</h2><p>Ученик без этого курса будет добавлен автоматически при отправке первого урока</p></div><button type="button" className="discord-send-select-all" disabled={!selectableIds.length} onClick={() => setSelected(allSelected ? [] : selectableIds)}>{allSelected ? "Снять выбор" : "Выбрать всех доступных"}</button></header>
      <div className="discord-course-invite">
        <div>
          <strong>Новый ученик ещё не на сервере?</strong>
          <span>Создай доступ для выбранного курса — получишь ссылку и персональный код. Ученик войдёт, нажмёт кнопку <b>«Получить доступ»</b> и введёт код — бот создаст его личное пространство. Без кода не откроется ни у кого.</span>
        </div>
        <button type="button" disabled={!courseId || inviteBusy} onClick={() => void generateInvite()}>
          {inviteBusy ? "Создаём…" : "Создать доступ"}
        </button>
      </div>
      {(invite || inviteError) && <div className="discord-course-invite-result">
        {invite ? <>
          <div className="discord-invite-code">
            <small>Код доступа — показывается один раз</small>
            <b>{invite.access_code}</b>
          </div>
          <input readOnly value={invite.invite_url} />
          <button type="button" onClick={() => void copyInvite()}>{inviteCopied ? "Скопировано" : "Скопировать всё"}</button>
          <small>Код одноразовый, привязан к курсу и действует 24 часа. Он хранится в зашифрованном виде — если потеряешь, создай доступ заново. «Скопировать всё» кладёт в буфер готовое сообщение для ученика.</small>
        </> : <span>{inviteError}</span>}
      </div>}
      {pendingInvites.length > 0 && <ul className="discord-invite-list">
        {pendingInvites.map((item) => <li key={item.invite_id} className="is-active">
          <span className="discord-invite-list__url">{item.invite_url}</span>
          <small className="discord-invite-list__meta">{inviteMeta(item)}</small>
          <span className="discord-invite-list__status">{inviteStatusLabel(item.status)}</span>
        </li>)}
      </ul>}
      {historyInvites.length > 0 && <div className="discord-invite-history">
        <button type="button" className="discord-invite-history__toggle" onClick={() => setInviteHistoryOpen((open) => !open)}>
          <span>История доступов · {historyInvites.length}</span>
          <i>{inviteHistoryOpen ? "▴" : "▾"}</i>
        </button>
        {inviteHistoryOpen && <ul className="discord-invite-list discord-invite-list--history">
          {historyInvites.map((item) => <li key={item.invite_id} className={`is-${item.status}`}>
            <span className="discord-invite-list__url">{item.invite_url}</span>
            <small className="discord-invite-list__meta">{inviteMeta(item)}</small>
            <span className="discord-invite-list__status">{inviteStatusLabel(item.status)}</span>
          </li>)}
        </ul>}
      </div>}
      {selectableMembers.length ? <div className="discord-send-recipients">
        {selectableMembers.map((member) => {
          const studentId = member.student_id!;
          const willJoin = newCourseMembers.some((item) => item.student_id === studentId);
          return <label key={studentId} className={selected.includes(studentId) ? "selected" : ""}>
            <input type="checkbox" checked={selected.includes(studentId)} onChange={() => toggle(studentId)} />
            <span className="discord-send-avatar">{member.avatar_url ? <img src={member.avatar_url} alt="" /> : initials(member.discord_display_name || member.student_name || "D")}</span>
            <span><strong>{member.discord_display_name || member.student_name}</strong><small>{member.thread_name || "Приватная ветка"}</small></span>
            <em className={willJoin ? "will-join" : "ready"}>{willJoin ? "Будет добавлен в курс" : "Готов к отправке"}</em>
          </label>;
        })}
      </div> : <div className="discord-send-empty">{lesson ? "Для этого урока пока нет доступных получателей" : "Сначала выберите опубликованный урок"}</div>}
      {notReachedMembers.length > 0 && <div className="discord-send-completed discord-send-completed--waiting">
        <header><div><strong>Ещё не дошли до этого урока</strong><span>Чтобы отправить выбранный урок, сначала переведите ученика на этот этап или выдайте текущий урок.</span></div><b>{notReachedMembers.length}</b></header>
        {notReachedMembers.map((member) => <article key={member.student_id!}>
          <span className="discord-send-avatar">{member.avatar_url ? <img src={member.avatar_url} alt="" /> : initials(member.discord_display_name || member.student_name || "D")}</span>
          <div><strong>{member.discord_display_name || member.student_name}</strong><small>{member.current_lesson_position ? `Сейчас урок ${member.current_lesson_position}; выбран урок ${lesson?.position}` : `Прогресс не задан; выбран урок ${lesson?.position}`}</small></div>
          <em className="waiting">Недоступен</em>
        </article>)}
      </div>}
      {passedMembers.length > 0 && <div className="discord-send-completed">
        <header><div><strong>Уже дальше по курсу</strong><span>Этим ученикам выбранный урок повторно не отправляется.</span></div><b>{passedMembers.length}</b></header>
        {passedMembers.map((member) => {
          const attempts = lessonSubmissions.filter((item) => item.student_id === member.student_id);
          const accepted = attempts.find((item) => item.status === "accepted");
          const latest = accepted || attempts[0];
          return <article key={member.student_id!}>
            <span className="discord-send-avatar">{member.avatar_url ? <img src={member.avatar_url} alt="" /> : initials(member.discord_display_name || member.student_name || "D")}</span>
            <div><strong>{member.discord_display_name || member.student_name}</strong><small>{accepted ? "Домашняя работа принята" : attempts.length ? "Работа по уроку уже отправлялась" : `Ученик уже перешёл к уроку ${member.current_lesson_position}`}</small></div>
            <em className={accepted ? "accepted" : "passed"}>{accepted ? "Принято" : `Сейчас урок ${member.current_lesson_position}`}</em>
            {latest && <button type="button" onClick={() => onSelectSubmission(latest)}>Открыть работу</button>}
          </article>;
        })}
      </div>}
    </section>

    {lesson && <section className="discord-send-card discord-send-preview">
      <header><b>3</b><div><h2>Предпросмотр сообщения</h2><p>Такое сообщение получит каждый выбранный ученик</p></div></header>
      <LessonPreview course={course!} lesson={lesson} />
    </section>}

    <div className="discord-send-action">
      <div><strong>{selected.length}</strong><span>{studentWord(selected.length)} получит задание</span></div>
      <button type="button" disabled={busy || !lesson || !selected.length} onClick={() => void send()}>{busy ? "Отправляем…" : selected.length ? `Отправить задание · ${selected.length}` : "Сначала выберите учеников"}</button>
    </div>
  </div>;
}

function LessonPreview({ course, lesson }: { course: CourseContent; lesson: LessonContent }) {
  return <article className="discord-send-preview__message">
    <h3>📘 Урок {lesson.position} · {lesson.title}</h3>
    <span>{course.title} · новый урок</span>
    {lesson.description && <p>{lesson.description}</p>}
    <strong>📝 Домашнее задание</strong>
    <blockquote>{lesson.assignment?.instructions}</blockquote>
    {lesson.video_source === "external_url" && lesson.video_reference && <a href={lesson.video_reference} target="_blank" rel="noreferrer">🎬 Смотреть материал →</a>}
    <small className="discord-send-preview__guide">Как сдать: отправь ответ сообщением в эту ветку — под ним появится кнопка «Отправить на проверку».</small>
  </article>;
}

function dispatchableLessons(course: CourseContent) {
  return course.lessons.filter((lesson) => lesson.is_published && lesson.assignment !== null);
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

function studentWord(count: number) {
  const lastTwo = count % 100;
  const last = count % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return "учеников";
  if (last === 1) return "ученик";
  if (last >= 2 && last <= 4) return "ученика";
  return "учеников";
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof APIError ? error.message : fallback;
}

function dispatchError(error: unknown) {
  if (!(error instanceof APIError)) return "Не удалось отправить задание";
  return {
    "recipients-not-eligible": "Список учеников изменился. Обновите страницу и повторите отправку.",
    "lesson-already-dispatched": "Это задание уже отправлено выбранным ученикам.",
    "published-lesson-required": "Сначала опубликуйте урок.",
    "assignment-required": "В выбранном уроке нет домашнего задания.",
  }[error.message] || error.message;
}
