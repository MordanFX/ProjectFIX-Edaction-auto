import { useEffect, useMemo, useState } from "react";

import {
  APIError,
  assignDiscordCourse,
  createDiscordLessonDispatch,
  getCourse,
} from "../api";
import type {
  CourseContent,
  CourseOverview,
  DiscordLessonDispatch,
  DiscordMemberOverview,
  LessonContent,
} from "../types";

interface DiscordDispatchModalProps {
  courses: CourseOverview[];
  members: DiscordMemberOverview[];
  initialCourseId?: string;
  initialLessonId?: string;
  onClose: () => void;
  onSent: (dispatch: DiscordLessonDispatch) => Promise<void>;
  onParticipantsChanged: () => Promise<void>;
}

export function DiscordDispatchModal({
  courses,
  members,
  initialCourseId,
  initialLessonId,
  onClose,
  onSent,
  onParticipantsChanged,
}: DiscordDispatchModalProps) {
  const [courseId, setCourseId] = useState(initialCourseId || courses[0]?.course_id || "");
  const [course, setCourse] = useState<CourseContent | null>(null);
  const [lessonId, setLessonId] = useState(initialLessonId || "");
  const [selected, setSelected] = useState<string[]>([]);
  const [currentMembers, setCurrentMembers] = useState(members);
  const [assigningStudents, setAssigningStudents] = useState<string[]>([]);
  const [showCourseAssignment, setShowCourseAssignment] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!courseId) return;
    let active = true;
    setLoading(true);
    setError(null);
    getCourse(courseId)
      .then((value) => {
        if (!active) return;
        setCourse(value);
        const lessons = dispatchableLessons(value);
        const preferred = lessons.find((lesson) => lesson.lesson_id === initialLessonId);
        setLessonId(preferred?.lesson_id || lessons[0]?.lesson_id || "");
        setSelected([]);
      })
      .catch((caught) => {
        if (active) setError(messageFromError(caught, "Не удалось загрузить курс"));
      })
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [courseId, initialLessonId]);

  useEffect(() => {
    setCurrentMembers(members);
  }, [members]);

  const lesson = course?.lessons.find((item) => item.lesson_id === lessonId) || null;
  const eligible = useMemo(
    () => currentMembers.filter((member) =>
      member.student_id
      && member.channel_id
      && member.status === "active"
      && member.course_id === courseId
      && member.current_lesson_position === lesson?.position,
    ),
    [currentMembers, courseId, lesson?.position],
  );
  const assignable = useMemo(
    () => currentMembers.filter((member) =>
      member.student_id
      && member.channel_id
      && member.is_guild_member
      && !(member.status === "active" && member.course_id === courseId)),
    [currentMembers, courseId],
  );
  const courseMembersOnOtherLessons = useMemo(
    () => currentMembers.filter((member) =>
      member.student_id
      && member.status === "active"
      && member.course_id === courseId
      && member.current_lesson_position !== lesson?.position),
    [currentMembers, courseId, lesson?.position],
  );

  function toggleStudent(studentId: string) {
    setSelected((current) => current.includes(studentId)
      ? current.filter((item) => item !== studentId)
      : [...current, studentId]);
  }

  async function send() {
    if (!lesson || !selected.length) {
      setError("Выбери урок и хотя бы одного получателя");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const dispatch = await createDiscordLessonDispatch({
        lesson_id: lesson.lesson_id,
        student_ids: selected,
        custom_message: null,
      });
      await onSent(dispatch);
    } catch (caught) {
      setError(dispatchError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function assignToCourse() {
    if (!courseId || !assigningStudents.length) return;
    setAssignBusy(true);
    setError(null);
    try {
      let updatedMembers = currentMembers;
      for (const studentId of assigningStudents) {
        const updated = await assignDiscordCourse(studentId, courseId);
        updatedMembers = updated.members;
      }
      setCurrentMembers(updatedMembers);
      const newlyEligible = updatedMembers
        .filter((member) =>
          member.student_id
          && assigningStudents.includes(member.student_id)
          && member.status === "active"
          && member.course_id === courseId
          && member.current_lesson_position === lesson?.position)
        .flatMap((member) => member.student_id ? [member.student_id] : []);
      setSelected((current) => [...new Set([...current, ...newlyEligible])]);
      setAssigningStudents([]);
      setShowCourseAssignment(false);
      await onParticipantsChanged();
    } catch (caught) {
      setError(messageFromError(caught, "Не удалось назначить курс"));
    } finally {
      setAssignBusy(false);
    }
  }

  const lessons = course ? dispatchableLessons(course) : [];
  const allSelected = eligible.length > 0
    && eligible.every((member) => member.student_id && selected.includes(member.student_id));

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="discord-dispatch-modal">
      <button className="modal-close" onClick={onClose}>×</button>
      <header>
        <p className="eyebrow">Discord-рассылка</p>
        <h2>Выдать домашнее задание</h2>
        <span>Бот отправит отдельное сообщение в приватную ветку каждого выбранного ученика.</span>
      </header>

      <div className="discord-dispatch-steps">
        <section>
          <div className="discord-dispatch-step-title"><b>1</b><div><strong>Курс и урок</strong><span>Доступны только опубликованные уроки с ДЗ</span></div></div>
          <div className="discord-dispatch-fields">
            <label><span>Discord-курс</span><select value={courseId} onChange={(event) => setCourseId(event.target.value)}>{courses.map((item) => <option key={item.course_id} value={item.course_id}>{item.title}</option>)}</select></label>
            <label><span>Урок</span><select value={lessonId} disabled={loading || !lessons.length} onChange={(event) => { setLessonId(event.target.value); setSelected([]); }}>{lessons.length ? lessons.map((item) => <option key={item.lesson_id} value={item.lesson_id}>Урок {item.position} · {item.title}</option>) : <option value="">Нет опубликованных уроков с ДЗ</option>}</select></label>
          </div>
        </section>

        <section>
          <div className="discord-dispatch-step-title"><b>2</b><div><strong>Получатели</strong><span>Только активные ученики, находящиеся на выбранном уроке</span></div></div>
          <div className="discord-recipient-toolbar"><span>Подходит: {eligible.length}</span><button type="button" disabled={!eligible.length} onClick={() => setSelected(allSelected ? [] : eligible.flatMap((member) => member.student_id ? [member.student_id] : []))}>{allSelected ? "Снять выбор" : "Выбрать всех"}</button></div>
          {eligible.length ? <div className="discord-recipient-list">{eligible.map((member) => <label key={member.student_id!}><input type="checkbox" checked={selected.includes(member.student_id!)} onChange={() => toggleStudent(member.student_id!)} /><img src={member.avatar_url || ""} alt="" /><span><strong>{member.discord_display_name || member.student_name}</strong><small>{member.thread_name || "Личная ветка"}</small></span></label>)}</div> : <div className="discord-dispatch-empty">В этом курсе пока нет учеников на выбранном уроке.</div>}
          {courseMembersOnOtherLessons.length > 0 && <div className="discord-ineligible-members"><span>Ещё не дошли до выбранного урока</span>{courseMembersOnOtherLessons.map((member) => <article key={member.student_id!}><img src={member.avatar_url || ""} alt="" /><div><strong>{member.discord_display_name || member.student_name}</strong><small>Сейчас на уроке {member.current_lesson_position}; выбран урок {lesson?.position}</small></div></article>)}</div>}
          {assignable.length > 0 && <div className="discord-course-assignment"><button type="button" className="discord-course-assignment__toggle" onClick={() => setShowCourseAssignment((value) => !value)}>{showCourseAssignment ? "Скрыть назначение курса" : "+ Добавить учеников в этот курс"}</button>{showCourseAssignment && <div className="discord-course-assignment__body"><p>Выбранным ученикам будет назначен курс «{course?.title}», прогресс начнётся с первого урока.</p><div className="discord-recipient-list">{assignable.map((member) => <label key={member.student_id!}><input type="checkbox" checked={assigningStudents.includes(member.student_id!)} onChange={() => setAssigningStudents((current) => current.includes(member.student_id!) ? current.filter((item) => item !== member.student_id) : [...current, member.student_id!])} /><img src={member.avatar_url || ""} alt="" /><span><strong>{member.discord_display_name || member.student_name}</strong><small>{member.course_title ? `Сейчас: ${member.course_title}` : "Без курса"}</small></span></label>)}</div><div className="discord-course-assignment__actions"><button type="button" disabled={assignBusy || !assigningStudents.length} onClick={() => void assignToCourse()}>{assignBusy ? "Назначаем…" : `Назначить курс · ${assigningStudents.length}`}</button></div></div>}</div>}
        </section>

        {lesson && <details className="discord-dispatch-preview-details"><summary>Посмотреть сообщение перед отправкой</summary><DispatchPreview course={course!} lesson={lesson} /></details>}
      </div>
      {error && <div className="form-error">{error}</div>}
      <footer><span>Будет отправлено: <b>{selected.length}</b></span><button type="button" onClick={onClose}>Отмена</button><button className="course-save-button" disabled={busy || !lesson || !selected.length} onClick={() => void send()}>{busy ? "Создаём рассылку…" : `Отправить ${selected.length || ""}`}</button></footer>
    </section>
  </div>;
}

function DispatchPreview({ course, lesson }: { course: CourseContent; lesson: LessonContent }) {
  return <div className="discord-dispatch-preview"><article><strong>Новый урок · {course.title}</strong><h3>Урок {lesson.position}: {lesson.title}</h3>{lesson.description && <p>{lesson.description}</p>}<b>Домашнее задание</b><p>{lesson.assignment?.instructions}</p>{lesson.video_source === "external_url" && lesson.video_reference && <a href={lesson.video_reference} target="_blank" rel="noreferrer">{lesson.video_reference}</a>}</article></div>;
}

function dispatchableLessons(course: CourseContent) {
  return course.lessons.filter((lesson) => lesson.is_published && lesson.assignment !== null);
}

function messageFromError(error: unknown, fallback: string) {
  return error instanceof APIError ? error.message : fallback;
}

function dispatchError(error: unknown) {
  if (!(error instanceof APIError)) return "Не удалось создать рассылку";
  return {
    "recipients-not-eligible": "Некоторые ученики уже не подходят для этого урока. Обнови список.",
    "lesson-already-dispatched": "Это задание уже было отправлено выбранным ученикам.",
    "published-lesson-required": "Сначала опубликуй урок.",
    "assignment-required": "В уроке нет домашнего задания.",
  }[error.message] || error.message;
}
