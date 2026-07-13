import { useEffect, useMemo, useState } from "react";

import { getCourse } from "../api";
import type { CourseContent, CourseOverview, LessonContent } from "../types";

interface ImportableLesson {
  course: CourseOverview;
  lesson: LessonContent;
}

interface LessonImportModalProps {
  courses: CourseOverview[];
  targetCourseId: string;
  onClose: () => void;
  onImport: (lessonId: string) => Promise<void>;
}

export function LessonImportModal({
  courses,
  targetCourseId,
  onClose,
  onImport,
}: LessonImportModalProps) {
  const [contents, setContents] = useState<CourseContent[]>([]);
  const [query, setQuery] = useState("");
  const [audience, setAudience] = useState<"all" | CourseOverview["audience"]>("all");
  const [onlyHomework, setOnlyHomework] = useState(false);
  const [busyLessonId, setBusyLessonId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all(courses.map((course) => getCourse(course.course_id)))
      .then((loaded) => {
        if (active) setContents(loaded);
      })
      .catch(() => {
        if (active) setError("Не удалось загрузить уроки из базы знаний");
      });
    return () => {
      active = false;
    };
  }, [courses]);

  const lessons = useMemo<ImportableLesson[]>(() => {
    const courseById = new Map(courses.map((course) => [course.course_id, course]));
    return contents.flatMap((content) => {
      const course = courseById.get(content.course_id);
      if (!course) return [];
      return content.lessons.map((lesson) => ({ course, lesson }));
    });
  }, [contents, courses]);

  const visibleLessons = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return lessons.filter(({ course, lesson }) => {
      if (course.course_id === targetCourseId) return false;
      if (audience !== "all" && course.audience !== audience) return false;
      if (onlyHomework && lesson.assignment === null) return false;
      if (!normalizedQuery) return true;
      return [
        course.title,
        course.description,
        lesson.title,
        lesson.description,
        lesson.assignment?.instructions,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });
  }, [audience, lessons, onlyHomework, query, targetCourseId]);

  async function handleImport(lessonId: string) {
    setBusyLessonId(lessonId);
    setError(null);
    try {
      await onImport(lessonId);
      onClose();
    } catch {
      setError("Не удалось добавить урок в курс");
    } finally {
      setBusyLessonId(null);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="lesson-import-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Выбрать урок из базы знаний"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}>×</button>
        <header>
          <span>База знаний</span>
          <h2>Добавить урок из базы</h2>
          <p>Урок будет скопирован в текущий курс. Исходный урок не изменится.</p>
        </header>

        <div className="lesson-import-filters">
          <label>
            <span>Поиск</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Название, курс или текст ДЗ"
            />
          </label>
          <label>
            <span>Источник</span>
            <select
              value={audience}
              onChange={(event) => setAudience(event.target.value as typeof audience)}
            >
              <option value="all">Все</option>
              <option value="telegram">Telegram</option>
              <option value="discord">Discord</option>
            </select>
          </label>
          <label className="lesson-import-check">
            <input
              type="checkbox"
              checked={onlyHomework}
              onChange={(event) => setOnlyHomework(event.target.checked)}
            />
            <span>Только с ДЗ</span>
          </label>
        </div>

        {error && <div className="form-error lesson-import-error">{error}</div>}

        <div className="lesson-import-list">
          {visibleLessons.length ? (
            visibleLessons.map(({ course, lesson }) => (
              <article key={lesson.lesson_id}>
                <div>
                  <span className={`lesson-import-source lesson-import-source--${course.audience}`}>
                    {course.audience === "telegram" ? "Telegram" : "Discord"}
                  </span>
                  <strong>Урок {lesson.position}: {lesson.title}</strong>
                  <small>{course.title}</small>
                  <p>{lesson.description || lesson.assignment?.instructions || "Описание пока не заполнено."}</p>
                </div>
                <footer>
                  <span>{lesson.assignment ? "Есть ДЗ" : "Без ДЗ"}</span>
                  <span>{lesson.is_published ? "Опубликован" : "Черновик"}</span>
                  <button
                    type="button"
                    disabled={busyLessonId === lesson.lesson_id}
                    onClick={() => void handleImport(lesson.lesson_id)}
                  >
                    {busyLessonId === lesson.lesson_id ? "Добавляем..." : "Выбрать"}
                  </button>
                </footer>
              </article>
            ))
          ) : (
            <div className="lesson-import-empty">
              {contents.length ? "Подходящих уроков не найдено." : "Загружаю уроки..."}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
