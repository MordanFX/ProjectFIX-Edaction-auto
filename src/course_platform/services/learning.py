"""Read-side use cases for sequential course delivery."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    Enrollment,
    Lesson,
    LessonMaterial,
    LessonMaterialProgress,
    LessonProgress,
    StaffUser,
    Student,
)
from course_platform.models.enums import (
    EnrollmentStatus,
    LessonProgressStatus,
    SubmissionKind,
    UnlockRule,
    VideoSource,
)
from course_platform.services.progression import ProgressionService


@dataclass(frozen=True, slots=True)
class LessonMaterialItem:
    material_id: UUID
    position: int
    title: str
    description: str | None
    kind: str
    video_source: VideoSource
    video_reference: str | None
    is_viewed: bool


@dataclass(frozen=True, slots=True)
class CurrentLesson:
    lesson_id: UUID
    course_title: str
    position: int
    total_lessons: int
    title: str
    description: str | None
    video_source: VideoSource
    video_reference: str | None
    materials: tuple[LessonMaterialItem, ...]
    assignment_instructions: str | None
    submission_kind: SubmissionKind | None
    unlock_rule: UnlockRule
    progress_status: LessonProgressStatus
    viewed_at: datetime | None
    release_at: datetime | None
    requires_view_confirmation: bool
    is_current: bool


@dataclass(frozen=True, slots=True)
class CourseOutlineLesson:
    lesson_id: UUID
    position: int
    title: str
    is_current: bool
    is_available: bool


@dataclass(frozen=True, slots=True)
class CourseOutline:
    title: str
    description: str | None
    total_lessons: int
    lessons: tuple[CourseOutlineLesson, ...]


class CuratorVideoAccessError(PermissionError):
    pass


class LearningService:
    """Return only the lesson currently unlocked for an active enrollment."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_course_outline(self, telegram_user_id: int) -> CourseOutline | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Course, Enrollment.current_lesson_position)
                    .join(Cohort, Cohort.course_id == Course.id)
                    .join(Enrollment, Enrollment.cohort_id == Cohort.id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Student.is_active.is_(True),
                        Course.is_active.is_(True),
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            course, current_position = row
            lessons = list(
                await session.scalars(
                    select(Lesson)
                    .where(
                        Lesson.course_id == course.id,
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Lesson.position)
                )
            )
            return CourseOutline(
                title=course.title,
                description=course.description,
                total_lessons=len(lessons),
                lessons=tuple(
                    CourseOutlineLesson(
                        lesson_id=lesson.id,
                        position=lesson.position,
                        title=lesson.title,
                        is_current=lesson.position == current_position,
                        is_available=lesson.position <= current_position,
                    )
                    for lesson in lessons
                ),
            )

    async def list_video_lessons(self, telegram_user_id: int) -> tuple[tuple[UUID, str], ...]:
        async with self._session_factory() as session:
            staff = await session.scalar(
                select(StaffUser.id).where(
                    StaffUser.telegram_user_id == telegram_user_id,
                    StaffUser.is_active.is_(True),
                )
            )
            if staff is None:
                raise CuratorVideoAccessError
            rows = await session.execute(
                select(Lesson.id, Course.title, Lesson.position, Lesson.title)
                .join(Course, Course.id == Lesson.course_id)
                .where(Course.is_active.is_(True), Lesson.is_published.is_(True))
                .order_by(Course.title, Lesson.position)
            )
            return tuple((row[0], f"{row[1]} · урок {row[2]}: {row[3]}") for row in rows)

    async def attach_telegram_video(
        self, telegram_user_id: int, lesson_id: UUID, chat_id: int, message_id: int
    ) -> None:
        async with session_scope(self._session_factory) as session:
            staff = await session.scalar(
                select(StaffUser.id).where(
                    StaffUser.telegram_user_id == telegram_user_id,
                    StaffUser.is_active.is_(True),
                )
            )
            if staff is None:
                raise CuratorVideoAccessError
            lesson = await session.get(Lesson, lesson_id)
            if lesson is None:
                raise LookupError(lesson_id)
            lesson.video_source = VideoSource.TELEGRAM_CHANNEL
            lesson.video_reference = f"{chat_id}:{message_id}"

    async def get_current_lesson(self, telegram_user_id: int) -> CurrentLesson | None:
        async with session_scope(self._session_factory) as session:
            row = (
                await session.execute(
                    select(
                        Enrollment,
                        Lesson,
                        Course.id.label("course_id"),
                        Course.title.label("course_title"),
                        Course.unlock_rule,
                        Assignment.instructions,
                        Assignment.submission_kind,
                        LessonProgress,
                    )
                    .join(Cohort, Cohort.course_id == Course.id)
                    .join(Enrollment, Enrollment.cohort_id == Cohort.id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(
                        Lesson,
                        (Lesson.course_id == Course.id)
                        & (Lesson.position == Enrollment.current_lesson_position),
                    )
                    .outerjoin(Assignment, Assignment.lesson_id == Lesson.id)
                    .outerjoin(
                        LessonProgress,
                        (LessonProgress.enrollment_id == Enrollment.id)
                        & (LessonProgress.lesson_id == Lesson.id),
                    )
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Student.is_active.is_(True),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        Course.is_active.is_(True),
                        Lesson.is_published.is_(True),
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()

            if row is None:
                return None

            progress = await ProgressionService.ensure_current_available(
                session,
                enrollment=row.Enrollment,
                lesson=row.Lesson,
            )
            if progress.status in {
                LessonProgressStatus.LOCKED,
                LessonProgressStatus.COMPLETED,
            }:
                return None

            total_lessons = await session.scalar(
                select(func.count(Lesson.id)).where(
                    Lesson.course_id == row.course_id,
                    Lesson.is_published.is_(True),
                )
            )

            return CurrentLesson(
                lesson_id=row.Lesson.id,
                course_title=row.course_title,
                position=row.Lesson.position,
                total_lessons=total_lessons or 0,
                title=row.Lesson.title,
                description=row.Lesson.description,
                video_source=row.Lesson.video_source,
                video_reference=row.Lesson.video_reference,
                materials=await self._lesson_materials(
                    session, row.Lesson.id, row.Enrollment.id
                ),
                assignment_instructions=row.instructions,
                submission_kind=row.submission_kind,
                unlock_rule=row.unlock_rule,
                progress_status=progress.status,
                viewed_at=progress.viewed_at,
                release_at=progress.release_at,
                requires_view_confirmation=row.Lesson.requires_view_confirmation,
                is_current=True,
            )

    async def get_available_lesson(
        self,
        telegram_user_id: int,
        lesson_id: UUID,
    ) -> CurrentLesson | None:
        """Return the current or an already reached lesson without changing progress."""

        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        Enrollment,
                        Lesson,
                        Course.id.label("course_id"),
                        Course.title.label("course_title"),
                        Course.unlock_rule,
                        Assignment.instructions,
                        Assignment.submission_kind,
                        LessonProgress,
                    )
                    .join(Cohort, Cohort.course_id == Course.id)
                    .join(Enrollment, Enrollment.cohort_id == Cohort.id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(Lesson, Lesson.course_id == Course.id)
                    .outerjoin(Assignment, Assignment.lesson_id == Lesson.id)
                    .outerjoin(
                        LessonProgress,
                        (LessonProgress.enrollment_id == Enrollment.id)
                        & (LessonProgress.lesson_id == Lesson.id),
                    )
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Student.is_active.is_(True),
                        Course.is_active.is_(True),
                        Lesson.id == lesson_id,
                        Lesson.is_published.is_(True),
                        Lesson.position <= Enrollment.current_lesson_position,
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None

            is_current = row.Lesson.position == row.Enrollment.current_lesson_position
            total_lessons = await session.scalar(
                select(func.count(Lesson.id)).where(
                    Lesson.course_id == row.course_id,
                    Lesson.is_published.is_(True),
                )
            )
            return CurrentLesson(
                lesson_id=row.Lesson.id,
                course_title=row.course_title,
                position=row.Lesson.position,
                total_lessons=total_lessons or 0,
                title=row.Lesson.title,
                description=row.Lesson.description,
                video_source=row.Lesson.video_source,
                video_reference=row.Lesson.video_reference,
                materials=await self._lesson_materials(
                    session, row.Lesson.id, row.Enrollment.id
                ),
                assignment_instructions=row.instructions,
                submission_kind=row.submission_kind,
                unlock_rule=row.unlock_rule,
                progress_status=(
                    row.LessonProgress.status
                    if row.LessonProgress is not None
                    else (
                        LessonProgressStatus.AVAILABLE
                        if is_current
                        else LessonProgressStatus.COMPLETED
                    )
                ),
                viewed_at=(
                    row.LessonProgress.viewed_at if row.LessonProgress is not None else None
                ),
                release_at=(
                    row.LessonProgress.release_at if row.LessonProgress is not None else None
                ),
                requires_view_confirmation=row.Lesson.requires_view_confirmation,
                is_current=is_current,
            )

    @staticmethod
    async def _lesson_materials(
        session: AsyncSession, lesson_id: UUID, enrollment_id: UUID
    ) -> tuple[LessonMaterialItem, ...]:
        rows = list(
            await session.execute(
                select(LessonMaterial, LessonMaterialProgress.id.label("progress_id"))
                .outerjoin(
                    LessonMaterialProgress,
                    (LessonMaterialProgress.material_id == LessonMaterial.id)
                    & (LessonMaterialProgress.enrollment_id == enrollment_id),
                )
                .where(LessonMaterial.lesson_id == lesson_id)
                .order_by(LessonMaterial.position)
            )
        )
        return tuple(
            LessonMaterialItem(
                material_id=material.id,
                position=material.position,
                title=material.title,
                description=material.description,
                kind=material.kind,
                video_source=material.video_source,
                video_reference=material.video_reference,
                is_viewed=progress_id is not None,
            )
            for material, progress_id in rows
        )

    async def mark_material_viewed(
        self, telegram_user_id: int, material_id: UUID
    ) -> bool:
        """Record a student's explicit view confirmation without unlocking lessons."""

        async with session_scope(self._session_factory) as session:
            row = (
                await session.execute(
                    select(Enrollment.id.label("enrollment_id"), LessonMaterial.id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .join(Cohort, Cohort.id == Enrollment.cohort_id)
                    .join(Lesson, Lesson.course_id == Cohort.course_id)
                    .join(LessonMaterial, LessonMaterial.lesson_id == Lesson.id)
                    .where(
                        Student.telegram_user_id == telegram_user_id,
                        Student.is_active.is_(True),
                        Enrollment.status == EnrollmentStatus.ACTIVE,
                        LessonMaterial.id == material_id,
                        Lesson.position <= Enrollment.current_lesson_position,
                    )
                    .order_by(Enrollment.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return False
            progress = await session.scalar(
                select(LessonMaterialProgress).where(
                    LessonMaterialProgress.enrollment_id == row.enrollment_id,
                    LessonMaterialProgress.material_id == material_id,
                )
            )
            if progress is None:
                session.add(
                    LessonMaterialProgress(
                        enrollment_id=row.enrollment_id,
                        material_id=material_id,
                        viewed_at=datetime.now(UTC),
                    )
                )
            return True
