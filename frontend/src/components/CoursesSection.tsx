import { useState } from "react";

import type { CourseOverview } from "../types";
import { CourseCreatePanel } from "./CourseCreatePanel";

interface CoursesSectionProps {
  courses: CourseOverview[];
  onRefresh: () => Promise<void>;
  onSelect: (course: CourseOverview) => void;
}

export function CoursesSection({
  courses,
  onRefresh,
  onSelect,
}: CoursesSectionProps) {
  const [audience, setAudience] = useState<CourseOverview["audience"]>("telegram");
  const visibleCourses = courses.filter((course) => course.audience === audience);
  const totalStudents = visibleCourses.reduce(
    (total, course) => total + course.students_count,
    0,
  );
  const activeCourses = visibleCourses.filter((course) => course.is_active).length;

  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Раздельные программы</p>
          <h1>Курсы {audience === "telegram" ? "Telegram" : "Discord"}</h1>
          <p className="muted">
            Курсы и ученики разных платформ не смешиваются.
          </p>
        </div>
        <button className="secondary-button" onClick={() => void onRefresh()}>
          ↻ Обновить
        </button>
      </div>

      <div className="audience-tabs" role="tablist" aria-label="Поток курсов">
        <button className={audience === "telegram" ? "active" : ""} onClick={() => setAudience("telegram")}>Telegram <b>{courses.filter((course) => course.audience === "telegram").length}</b></button>
        <button className={audience === "discord" ? "active" : ""} onClick={() => setAudience("discord")}>Discord <b>{courses.filter((course) => course.audience === "discord").length}</b></button>
      </div>

      <div className="metrics-grid metrics-grid--courses">
        <MetricCard
          label="Активные курсы"
          value={activeCourses}
          accent
        />
        <MetricCard label="Курсов в потоке" value={visibleCourses.length} />
        <MetricCard label="Учеников на курсах" value={totalStudents} />
      </div>

      <CourseCreatePanel onCreated={onRefresh} />

      {visibleCourses.length ? (
        <section className="course-grid">
          {visibleCourses.map((course, index) => (
            <CourseCard
              key={course.course_id}
              course={course}
              index={index}
              onSelect={() => onSelect(course)}
            />
          ))}
        </section>
      ) : (
        <section className="review-filter-empty">
          Курсов для {audience === "telegram" ? "Telegram" : "Discord"} пока нет.
        </section>
      )}
    </>
  );
}

interface MetricCardProps {
  label: string;
  value: string | number;
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

interface CourseCardProps {
  course: CourseOverview;
  index: number;
  onSelect: () => void;
}

function CourseCard({ course, index, onSelect }: CourseCardProps) {
  return (
    <button
      className={`course-card course-card--${index % 3}`}
      onClick={onSelect}
    >
      <div className="course-card__cover">
        <span>{course.audience === "telegram" ? "Telegram" : "Discord"} · курс {String(index + 1).padStart(2, "0")}</span>
        <strong>{course.title}</strong>
      </div>
      <div className="course-card__body">
        <div className="course-card__status">
          <span
            className={`status-badge status-badge--${course.is_active ? "active" : "paused"}`}
          >
            {course.is_active ? "Активен" : "Черновик"}
          </span>
          <small>{unlockRuleLabel(course.unlock_rule)}</small>
        </div>
        <p>{course.description || "Описание курса пока не заполнено."}</p>
        <div className="course-stats">
          <span>
            <strong>{course.lessons_count}</strong> уроков
          </span>
          <span>
            <strong>{course.cohorts_count}</strong> групп
          </span>
          <span>
            <strong>{course.students_count}</strong> учеников
          </span>
        </div>
        <span className="course-card__action">Открыть конструктор →</span>
      </div>
    </button>
  );
}

function unlockRuleLabel(rule: CourseOverview["unlock_rule"]): string {
  return {
    after_view: "После просмотра",
    after_submission: "После сдачи ДЗ",
    after_acceptance: "После принятия ДЗ",
  }[rule];
}
