import type { DashboardSummary, StudentOverview } from "../types";

interface StudentsSectionProps {
  students: StudentOverview[];
  summary: DashboardSummary;
  onRefresh: () => Promise<void>;
  onSelect: (student: StudentOverview) => void;
}

export function StudentsSection({
  students,
  summary,
  onRefresh,
  onSelect,
}: StudentsSectionProps) {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Telegram-поток</p>
          <h1>Ученики Telegram</h1>
          <p className="muted">
            Только ученики Telegram-бота, их курсы, прогресс и домашние работы.
          </p>
        </div>
        <button className="secondary-button" onClick={() => void onRefresh()}>
          ↻ Обновить
        </button>
      </div>
      <div className="metrics-grid">
        <MetricCard label="Активные в Telegram" value={summary.active_students} accent />
        <MetricCard
          label="Средний прогресс"
          value={`${summary.average_progress_percent}%`}
        />
        <MetricCard
          label="Завершили курс"
          value={summary.completed_enrollments}
        />
      </div>
      {students.length ? (
        <section className="student-grid">
          {students.map((student) => (
            <StudentCard
              key={`${student.student_id}-${student.enrollment_id ?? "none"}`}
              student={student}
              onSelect={() => onSelect(student)}
            />
          ))}
        </section>
      ) : (
        <section className="review-filter-empty">
          Telegram-ученики появятся здесь после команды /start в боте.
        </section>
      )}
    </>
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

function StudentCard({
  student,
  onSelect,
}: {
  student: StudentOverview;
  onSelect: () => void;
}) {
  return (
    <button type="button" className="student-card" onClick={onSelect}>
      <header>
        <span className="student-avatar">{initials(student.name)}</span>
        <div>
          <h3>{student.name}</h3>
          <span>{student.username ? `@${student.username}` : "без username"}</span>
        </div>
        <EnrollmentStatus status={student.enrollment_status} />
      </header>
      {student.assigned_curator_id && (
        <span className="curator-pin curator-pin--assigned">Куратор: {student.assigned_curator_name}</span>
      )}
      <div className="student-course">
        <small>Текущий курс</small>
        <strong>{student.course_title ?? "Курс пока не назначен"}</strong>
        <span>{student.cohort_title ?? "Без группы"}</span>
      </div>
      <div className="progress-label">
        <span>Прогресс</span>
        <strong>{student.progress_percent}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${student.progress_percent}%` }} />
      </div>
      <footer>
        <span>
          Урок {student.current_lesson_position ?? "—"} из {student.total_lessons || "—"}
        </span>
        <span>
          Принято ДЗ: {student.accepted_submissions}/{student.total_assignments}
        </span>
        <strong>Подробнее →</strong>
      </footer>
    </button>
  );
}

function EnrollmentStatus({
  status,
}: {
  status: StudentOverview["enrollment_status"];
}) {
  const label = status
    ? {
        active: "Учится",
        paused: "Пауза",
        completed: "Завершён",
        revoked: "Доступ закрыт",
      }[status]
    : "Без курса";
  return (
    <span className={`status-badge status-badge--${status ?? "none"}`}>
      {label}
    </span>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}
