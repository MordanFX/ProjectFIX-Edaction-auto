import { useEffect, useMemo, useState } from "react";

import {
  APIError,
  decideReview,
  getCourses,
  getCurrentStaff,
  getDashboardSummary,
  getDiscordOverview,
  getReviewQueue,
  getStudents,
  hasSession,
  login,
  logout,
} from "./api";
import logo from "./assets/fix-logo.jpg";
import { LoadingScreen, LoginScreen } from "./components/AuthScreens";
import { CourseModal } from "./components/CourseModal";
import { CoursesSection } from "./components/CoursesSection";
import { CuratorCabinetSection } from "./components/CuratorCabinetSection";
import { DiscordAccessSection } from "./components/DiscordAccessSection";
import { DiscordCourseModal } from "./components/DiscordCourseModal";
import { DiscordDispatchSection } from "./components/DiscordDispatchSection";
import { DiscordSection } from "./components/DiscordSection";
import { DiscordStudentsSection } from "./components/DiscordStudentsSection";
import { KnowledgeBaseSection } from "./components/KnowledgeBaseSection";
import { ReviewModal } from "./components/ReviewModal";
import { ReviewsSection } from "./components/ReviewsSection";
import { StudentModal } from "./components/StudentModal";
import { StudentsSection } from "./components/StudentsSection";
import { TeamSection } from "./components/TeamSection";
import { TelegramQuestionsSection } from "./components/TelegramQuestionsSection";
import type {
  CourseOverview,
  DashboardSummary,
  DiscordWorkspaceOverview,
  ReviewQueueItem,
  ReviewVerdict,
  Staff,
  StudentOverview,
} from "./types";

type AppState = "loading" | "login" | "dashboard";
type Section =
  | "reviews"
  | "questions"
  | "discord"
  | "discord-dispatch"
  | "discord-students"
  | "discord-access"
  | "students"
  | "knowledge"
  | "courses"
  | "cabinet"
  | "team";

interface DashboardData {
  staff: Staff;
  queue: ReviewQueueItem[];
  discordQueue: ReviewQueueItem[];
  summary: DashboardSummary;
  students: StudentOverview[];
  courses: CourseOverview[];
  discord: DiscordWorkspaceOverview;
}

export function App() {
  const [state, setState] = useState<AppState>("loading");
  const [section, setSection] = useState<Section>("reviews");
  const [discordOpen, setDiscordOpen] = useState(false);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedReview, setSelectedReview] = useState<ReviewQueueItem | null>(null);
  const [selectedStudent, setSelectedStudent] = useState<StudentOverview | null>(null);
  const [selectedCourse, setSelectedCourse] = useState<CourseOverview | null>(null);
  const [discordDispatchRequest, setDiscordDispatchRequest] = useState<{ courseId: string; lessonId?: string } | null>(null);

  const pendingCount = useMemo(
    () =>
      data?.queue.filter(
        (item) => item.status === "submitted" || item.status === "in_review",
      ).length ?? 0,
    [data?.queue],
  );

  useEffect(() => {
    if (!hasSession()) {
      setState("login");
      return;
    }
    void loadDashboard().catch(() => {
      logout();
      setState("login");
    });
  }, []);

  useEffect(() => {
    const modalIsOpen = selectedReview || selectedStudent || selectedCourse;
    if (!modalIsOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeModals();
    };
    document.body.classList.add("modal-open");
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.classList.remove("modal-open");
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectedReview, selectedStudent, selectedCourse]);

  async function loadDashboard() {
    const [staff, queue, discordQueue, summary, students, courses, discord] = await Promise.all([
      getCurrentStaff(),
      getReviewQueue("telegram"),
      getReviewQueue("discord"),
      getDashboardSummary(),
      getStudents(),
      getCourses(),
      getDiscordOverview(),
    ]);
    setData({ staff, queue, discordQueue, summary, students, courses, discord });
    setError(null);
    setState("dashboard");
  }

  async function handleLogin(loginValue: string, password: string) {
    setError(null);
    await login(loginValue, password);
    await loadDashboard();
  }

  async function handleRefresh() {
    try {
      await loadDashboard();
    } catch (caughtError) {
      setError(messageFromError(caughtError, "Не удалось обновить данные"));
    }
  }

  async function handleDecision(
    item: ReviewQueueItem,
    verdict: ReviewVerdict,
    message: string,
    attachments?: File[],
  ) {
    try {
      await decideReview(item.submission_id, verdict, message, attachments);
      await loadDashboard();
      showNotice(
        verdict === "accepted"
          ? `Работа ${item.student_name} принята`
          : `Работа ${item.student_name} отправлена на доработку`,
      );
    } catch (caughtError) {
      const message = messageFromError(caughtError, "Не удалось сохранить решение");
      setError(message);
      throw caughtError;
    }
  }

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 3500);
  }

  function closeModals() {
    setSelectedReview(null);
    setSelectedStudent(null);
    setSelectedCourse(null);
  }

  function handleLogout() {
    logout();
    closeModals();
    setData(null);
    setState("login");
  }

  if (state === "loading") return <LoadingScreen />;
  if (state === "login") {
    return <LoginScreen onLogin={handleLogin} externalError={error} />;
  }
  if (!data) return <LoadingScreen />;

  return (
    <main className={`dashboard-shell dashboard-shell--reviews dashboard-shell--${section}`}>
      <aside className="fix-sidebar">
        <div className="fix-sidebar__brand">
          <img className="brand-logo brand-logo--topbar" src={logo} alt="FIX BY MRDN" />
          <div>
            <strong>FIX BY MRDN</strong>
            <small>CURATOR WORKSPACE</small>
          </div>
        </div>
        <nav className="fix-sidebar__nav" aria-label="Разделы кабинета">
          <button
            className={section === "reviews" ? "active" : ""}
            onClick={() => setSection("reviews")}
          >
            <i>01</i><b>Telegram ДЗ</b><span>{pendingCount}</span>
          </button>
          <button
            className={section === "students" ? "active" : ""}
            onClick={() => setSection("students")}
          >
            <i>02</i><b>Telegram ученики</b>
          </button>
          <button
            className={section === "questions" ? "active" : ""}
            onClick={() => setSection("questions")}
          >
            <i>03</i><b>Вопросы</b>
          </button>
          <button
            className={section === "courses" ? "active" : ""}
            onClick={() => setSection("courses")}
          >
            <i>04</i><b>Курсы</b>
          </button>
          <button
            className={section === "knowledge" ? "active" : ""}
            onClick={() => setSection("knowledge")}
          >
            <i>05</i><b>База знаний</b>
          </button>
          <button
            className={section === "cabinet" ? "active" : ""}
            onClick={() => setSection("cabinet")}
          >
            <i>06</i><b>Мой кабинет</b>
          </button>
          {data.staff.role === "admin" && (
            <button
              className={section === "team" ? "active" : ""}
              onClick={() => setSection("team")}
            >
              <i>07</i><b>Команда</b>
            </button>
          )}
          <div className="fix-sidebar__group">
            <button
              type="button"
              className="fix-sidebar__group-toggle"
              onClick={() => setDiscordOpen((value) => !value)}
            >
              <b>Discord · на паузе</b><i>{discordOpen ? "−" : "+"}</i>
            </button>
            {discordOpen && (
              <>
                <button
                  className={section === "discord" ? "active" : ""}
                  onClick={() => setSection("discord")}
                >
                  <i>D1</i><b>Discord</b><span>{data.discord.private_spaces}</span>
                </button>
                <button
                  className={section === "discord-dispatch" ? "active" : ""}
                  onClick={() => setSection("discord-dispatch")}
                >
                  <i>D2</i><b>Выдать ДЗ Discord</b>
                </button>
                <button
                  className={section === "discord-students" ? "active" : ""}
                  onClick={() => setSection("discord-students")}
                >
                  <i>D3</i><b>Discord ученики</b>
                </button>
                <button
                  className={section === "discord-access" ? "active" : ""}
                  onClick={() => setSection("discord-access")}
                >
                  <i>D4</i><b>Доступы</b>
                </button>
              </>
            )}
          </div>
        </nav>
        <div className="fix-sidebar__user">
          <span className="user-avatar">{initials(data.staff.display_name)}</span>
          <div>
            <strong>{data.staff.display_name}</strong>
            <small>Команда</small>
          </div>
          <button className="text-button" aria-label="Выйти" onClick={handleLogout}>↗</button>
        </div>
      </aside>

      <div className="fix-workspace">
        <header className="fix-workspace__bar">
          <span>PROJECT FIX / {section.toUpperCase()}</span>
          <button className="fix-logout" onClick={handleLogout}>Выйти ↗</button>
        </header>
        <section className="dashboard-content">
          {error && <div className="page-error">{error}</div>}
          {notice && <div className="toast">✓ {notice}</div>}
          {section === "reviews" && <ReviewsSection queue={data.queue} summary={data.summary} staffId={data.staff.id} onRefresh={handleRefresh} onSelect={setSelectedReview} />}
          {section === "questions" && <TelegramQuestionsSection />}
          {section === "discord" && (
            <DiscordSection
              overview={data.discord}
              queue={data.discordQueue}
              courses={data.courses.filter((course) => course.audience === "discord")}
              onRefresh={handleRefresh}
              onSelect={setSelectedReview}
              onOpenCourse={setSelectedCourse}
            />
          )}
          {section === "discord-dispatch" && (
            <DiscordDispatchSection
              courses={data.courses.filter((course) => course.audience === "discord")}
              members={data.discord.members}
              submissions={data.discordQueue}
              initialRequest={discordDispatchRequest}
              onRequestHandled={() => setDiscordDispatchRequest(null)}
              onChanged={handleRefresh}
              onSelectSubmission={setSelectedReview}
            />
          )}
          {section === "discord-students" && (
            <DiscordStudentsSection
              overview={data.discord}
              courses={data.courses.filter((course) => course.audience === "discord")}
              submissions={data.discordQueue}
              onChanged={handleRefresh}
              onSelectSubmission={setSelectedReview}
            />
          )}
          {section === "discord-access" && <DiscordAccessSection />}
          {section === "students" && <StudentsSection students={data.students} summary={data.summary} onRefresh={handleRefresh} onSelect={setSelectedStudent} />}
          {section === "knowledge" && <KnowledgeBaseSection courses={data.courses} onOpenCourse={setSelectedCourse} />}
          {section === "courses" && <CoursesSection courses={data.courses} onRefresh={handleRefresh} onSelect={setSelectedCourse} />}
          {section === "cabinet" && (
            <CuratorCabinetSection
              staff={data.staff}
              queue={data.queue}
              discordQueue={data.discordQueue}
              onSelect={setSelectedReview}
            />
          )}
          {section === "team" && <TeamSection />}
        </section>
      </div>

      {selectedReview && (
        <ReviewModal
          item={selectedReview}
          staff={data.staff}
          onChanged={handleRefresh}
          onClose={() => setSelectedReview(null)}
          onDecision={handleDecision}
        />
      )}
      {selectedStudent && (
        <StudentModal
          overview={selectedStudent}
          courses={data.courses.filter((course) => course.audience === "telegram")}
          onClose={() => setSelectedStudent(null)}
          onChanged={handleRefresh}
        />
      )}
      {selectedCourse && (
        selectedCourse.audience === "discord" ? (
          <DiscordCourseModal
            overview={selectedCourse}
            knowledgeCourses={data.courses}
            onClose={() => setSelectedCourse(null)}
            onChanged={handleRefresh}
            onDispatchLesson={(courseId, lessonId) => {
              setSelectedCourse(null);
              setSection("discord-dispatch");
              setDiscordDispatchRequest({ courseId, lessonId });
            }}
          />
        ) : (
          <CourseModal
            overview={selectedCourse}
            knowledgeCourses={data.courses}
            onClose={() => setSelectedCourse(null)}
            onChanged={handleRefresh}
            onDispatchLesson={(courseId, lessonId) => {
              setSelectedCourse(null);
              setSection("discord-dispatch");
              setDiscordDispatchRequest({ courseId, lessonId });
            }}
          />
        )
      )}
    </main>
  );
}

function messageFromError(error: unknown, fallback: string): string {
  return error instanceof APIError ? error.message : fallback;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}
