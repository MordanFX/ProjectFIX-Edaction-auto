import { useEffect, useMemo, useState } from "react";

import { getCourse, getLessonCover } from "../api";
import type { CourseContent, CourseOverview, LessonContent } from "../types";

type AudienceFilter = "all" | CourseOverview["audience"];
type ContentFilter = "all" | "with-homework" | "published" | "draft";

interface KnowledgeLesson {
  course: CourseOverview;
  lesson: LessonContent;
}

interface KnowledgeBaseSectionProps {
  courses: CourseOverview[];
  onOpenCourse: (course: CourseOverview) => void;
}

export function KnowledgeBaseSection({
  courses,
  onOpenCourse,
}: KnowledgeBaseSectionProps) {
  const [courseContents, setCourseContents] = useState<CourseContent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [audience, setAudience] = useState<AudienceFilter>("all");
  const [contentFilter, setContentFilter] = useState<ContentFilter>("all");
  const [selectedLesson, setSelectedLesson] = useState<KnowledgeLesson | null>(null);
  const [remoteCovers, setRemoteCovers] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;

    async function loadCourses() {
      setIsLoading(true);
      setError(null);
      try {
        const contents = await Promise.all(courses.map((course) => getCourse(course.course_id)));
        if (!cancelled) {
          setCourseContents(contents);
        }
      } catch {
        if (!cancelled) {
          setError("Не удалось загрузить базу знаний");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadCourses();

    return () => {
      cancelled = true;
    };
  }, [courses]);

  useEffect(() => {
    if (!selectedLesson) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedLesson(null);
    };
    document.body.classList.add("modal-open");
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.classList.remove("modal-open");
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectedLesson]);

  const lessons = useMemo<KnowledgeLesson[]>(() => {
    const courseById = new Map(courses.map((course) => [course.course_id, course]));
    return courseContents.flatMap((content) => {
      const overview = courseById.get(content.course_id);
      if (!overview) return [];
      return content.lessons.map((lesson) => ({ course: overview, lesson }));
    });
  }, [courseContents, courses]);

  const filteredLessons = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return lessons.filter(({ course, lesson }) => {
      if (audience !== "all" && course.audience !== audience) return false;
      if (contentFilter === "with-homework" && lesson.assignment === null) return false;
      if (contentFilter === "published" && !lesson.is_published) return false;
      if (contentFilter === "draft" && lesson.is_published) return false;
      if (!normalizedQuery) return true;
      const searchSource = [
        course.title,
        course.description,
        lesson.title,
        lesson.description,
        lesson.assignment?.instructions,
        lesson.video_reference,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return searchSource.includes(normalizedQuery);
    });
  }, [audience, contentFilter, lessons, query]);

  const stats = useMemo(
    () => ({
      total: lessons.length,
      telegram: lessons.filter((item) => item.course.audience === "telegram").length,
      discord: lessons.filter((item) => item.course.audience === "discord").length,
      homework: lessons.filter((item) => item.lesson.assignment !== null).length,
    }),
    [lessons],
  );

  useEffect(() => {
    const candidates = lessons.filter(
      ({ lesson }) =>
        localLessonCoverUrl(lesson) === null
        && lesson.video_source === "external_url"
        && lesson.video_reference
        && remoteCovers[lesson.lesson_id] === undefined,
    );
    if (candidates.length === 0) return;

    let cancelled = false;
    async function loadRemoteCovers() {
      const results = await Promise.allSettled(
        candidates.map(async ({ lesson }) => ({
          lessonId: lesson.lesson_id,
          cover: await getLessonCover(lesson.lesson_id),
        })),
      );
      if (cancelled) return;
      setRemoteCovers((current) => {
        const next = { ...current };
        for (const result of results) {
          if (result.status === "fulfilled") {
            next[result.value.lessonId] = result.value.cover.cover_url ?? "";
          }
        }
        return next;
      });
    }

    void loadRemoteCovers();
    return () => {
      cancelled = true;
    };
  }, [lessons, remoteCovers]);

  return (
    <>
      <div className="page-heading knowledge-heading">
        <div>
          <p className="eyebrow">Материалы и уроки</p>
          <h1>База знаний</h1>
          <p className="muted">
            Общий каталог уроков из Telegram и Discord-курсов. Пока это просмотр и
            навигация без изменения текущей логики выдачи.
          </p>
        </div>
      </div>

      <div className="metrics-grid knowledge-metrics">
        <MetricCard label="Всего уроков" value={stats.total} accent />
        <MetricCard label="Telegram" value={stats.telegram} />
        <MetricCard label="Discord" value={stats.discord} />
        <MetricCard label="С домашним заданием" value={stats.homework} />
      </div>

      <section className="knowledge-board">
        <header>
          <div>
            <p className="eyebrow">Каталог</p>
            <h2>Уроки</h2>
          </div>
          <span>{filteredLessons.length} из {lessons.length}</span>
        </header>

        <div className="knowledge-filters">
          <label className="knowledge-filters__search">
            <span>Поиск</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Название урока, курс, текст ДЗ"
            />
          </label>
          <label>
            <span>Источник</span>
            <select
              value={audience}
              onChange={(event) => setAudience(event.target.value as AudienceFilter)}
            >
              <option value="all">Все источники</option>
              <option value="telegram">Telegram</option>
              <option value="discord">Discord</option>
            </select>
          </label>
          <label>
            <span>Тип</span>
            <select
              value={contentFilter}
              onChange={(event) => setContentFilter(event.target.value as ContentFilter)}
            >
              <option value="all">Все уроки</option>
              <option value="with-homework">С ДЗ</option>
              <option value="published">Опубликованные</option>
              <option value="draft">Черновики</option>
            </select>
          </label>
        </div>

        {error && <div className="form-error knowledge-error">{error}</div>}

        {isLoading ? (
          <div className="knowledge-empty">Загружаю уроки...</div>
        ) : filteredLessons.length ? (
          <div className="knowledge-card-grid">
            {filteredLessons.map((item) => (
              <KnowledgeLessonCard
                key={item.lesson.lesson_id}
                item={item}
                coverUrl={
                  localLessonCoverUrl(item.lesson)
                  ?? remoteCovers[item.lesson.lesson_id]
                  ?? null
                }
                onSelect={() => setSelectedLesson(item)}
                onOpenCourse={() => onOpenCourse(item.course)}
              />
            ))}
          </div>
        ) : (
          <div className="knowledge-empty">
            Ничего не найдено. Измени фильтры или поисковый запрос.
          </div>
        )}
      </section>

      {selectedLesson && (
        <KnowledgeLessonModal
          item={selectedLesson}
          onClose={() => setSelectedLesson(null)}
          onOpenCourse={() => {
            setSelectedLesson(null);
            onOpenCourse(selectedLesson.course);
          }}
        />
      )}
    </>
  );
}

interface MetricCardProps {
  label: string;
  value: number;
  accent?: boolean;
}

function MetricCard({ label, value, accent = false }: MetricCardProps) {
  return (
    <article className={`metric-card ${accent ? "metric-card--accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

interface KnowledgeLessonCardProps {
  item: KnowledgeLesson;
  coverUrl: string | null;
  onSelect: () => void;
  onOpenCourse: () => void;
}

function KnowledgeLessonCard({
  item,
  coverUrl,
  onSelect,
  onOpenCourse,
}: KnowledgeLessonCardProps) {
  const { course, lesson } = item;
  const hasCoverImage = Boolean(coverUrl);
  return (
    <article className="knowledge-card">
      <button
        className={[
          "knowledge-card__cover",
          `knowledge-card__cover--${course.audience}`,
          hasCoverImage ? "knowledge-card__cover--image" : "",
        ].join(" ")}
        style={
          coverUrl
            ? {
                backgroundImage:
                  `linear-gradient(135deg, rgb(4 12 22 / 42%), rgb(6 11 18 / 84%)), url(${coverUrl})`,
              }
            : undefined
        }
        onClick={onSelect}
        aria-label={`Открыть урок ${lesson.title}`}
      >
        <span>{audienceLabel(course.audience)}</span>
        <strong>{String(lesson.position).padStart(2, "0")}</strong>
        <small>{course.title}</small>
      </button>
      <button className="knowledge-card__main" onClick={onSelect}>
        <span className={`knowledge-card__source knowledge-card__source--${course.audience}`}>
          {audienceLabel(course.audience)}
        </span>
        <span className="knowledge-card__lesson">Урок {lesson.position}</span>
        <strong>{lesson.title}</strong>
        <small>{course.title}</small>
        <p>{lesson.description || lesson.assignment?.instructions || "Описание пока не заполнено."}</p>
      </button>
      <div className="knowledge-card__meta">
        <span className={`knowledge-chip ${lesson.is_published ? "is-ready" : "is-draft"}`}>
          {lesson.is_published ? "Опубликован" : "Черновик"}
        </span>
        {lesson.assignment && <span className="knowledge-chip is-homework">Есть ДЗ</span>}
      </div>
      <footer>
        <button onClick={onSelect}>Посмотреть</button>
        <button onClick={onOpenCourse}>Открыть курс</button>
      </footer>
    </article>
  );
}

interface KnowledgeLessonModalProps {
  item: KnowledgeLesson;
  onClose: () => void;
  onOpenCourse: () => void;
}

function KnowledgeLessonModal({
  item,
  onClose,
  onOpenCourse,
}: KnowledgeLessonModalProps) {
  const { course, lesson } = item;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <article
        className="knowledge-modal"
        role="dialog"
        aria-modal="true"
        aria-label={lesson.title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="modal-close" onClick={onClose} aria-label="Закрыть">×</button>
        <header>
          <span>{audienceLabel(course.audience)} · {course.title}</span>
          <h2>Урок {lesson.position}: {lesson.title}</h2>
          <p>{lesson.description || "Описание урока пока не заполнено."}</p>
        </header>

        <div className="knowledge-modal__body">
          <section>
            <h3>Материал</h3>
            <dl className="knowledge-facts">
              <div>
                <dt>Статус</dt>
                <dd>{lesson.is_published ? "Опубликован" : "Черновик"}</dd>
              </div>
              <div>
                <dt>Видео</dt>
                <dd>{videoLabel(lesson.video_source)}</dd>
              </div>
              <div>
                <dt>Подтверждение просмотра</dt>
                <dd>{lesson.requires_view_confirmation ? "Требуется" : "Не требуется"}</dd>
              </div>
            </dl>
            {lesson.video_reference && (
              <a
                className="knowledge-link"
                href={lesson.video_reference}
                target="_blank"
                rel="noreferrer"
              >
                Открыть ссылку на материал ↗
              </a>
            )}
          </section>

          <section>
            <h3>Домашнее задание</h3>
            {lesson.assignment ? (
              <div className="knowledge-homework">
                <p>{lesson.assignment.instructions || "Инструкция пока не заполнена."}</p>
                <small>
                  Формат: {submissionKindLabel(lesson.assignment.submission_kind)} ·{" "}
                  {lesson.assignment.is_required ? "обязательное" : "необязательное"}
                </small>
              </div>
            ) : (
              <div className="knowledge-homework knowledge-homework--empty">
                В этом уроке нет домашнего задания.
              </div>
            )}
          </section>

          {lesson.materials.length > 0 && (
            <section>
              <h3>Дополнительные материалы</h3>
              <div className="knowledge-materials">
                {lesson.materials.map((material) => (
                  <article key={material.material_id}>
                    <strong>{material.position}. {material.title}</strong>
                    <span>{material.description || "Без описания"}</span>
                    {material.video_reference && (
                      <a href={material.video_reference} target="_blank" rel="noreferrer">
                        Открыть ↗
                      </a>
                    )}
                  </article>
                ))}
              </div>
            </section>
          )}
        </div>

        <footer>
          <button onClick={onOpenCourse}>Открыть курс</button>
          <button className="primary" onClick={onClose}>Закрыть</button>
        </footer>
      </article>
    </div>
  );
}

function audienceLabel(audience: CourseOverview["audience"]): string {
  return audience === "telegram" ? "Telegram" : "Discord";
}

function videoLabel(source: LessonContent["video_source"]): string {
  return {
    placeholder: "Без видео",
    telegram_channel: "Telegram-канал",
    external_url: "Внешняя ссылка",
  }[source];
}

function localLessonCoverUrl(lesson: LessonContent): string | null {
  const image = lesson.materials.find(
    (material) => material.kind === "image" && material.video_reference,
  );
  if (!image?.video_reference) return null;
  const reference = image.video_reference.trim();
  if (reference.startsWith("http://") || reference.startsWith("https://") || reference.startsWith("/")) {
    return reference;
  }
  const publicPrefix = "frontend/public/";
  if (reference.startsWith(publicPrefix)) {
    return `/${reference.slice(publicPrefix.length)}`;
  }
  return `/${reference}`;
}

function submissionKindLabel(kind: NonNullable<LessonContent["assignment"]>["submission_kind"]): string {
  return {
    text: "текст",
    file: "файл",
    photo: "фото",
    video: "видео",
    any: "любой",
  }[kind];
}
