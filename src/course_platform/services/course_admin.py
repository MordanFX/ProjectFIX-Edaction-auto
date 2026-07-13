"""Authenticated course content management use cases."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from course_platform.db.session import session_scope
from course_platform.models import (
    Assignment,
    Cohort,
    Course,
    CourseReminderStep,
    Enrollment,
    Lesson,
    LessonMaterial,
    LessonProgress,
    LessonReminder,
)
from course_platform.models.enums import (
    CourseAudience,
    EnrollmentStatus,
    LessonProgressStatus,
    ReminderKind,
    ReminderStatus,
    SubmissionKind,
    UnlockRule,
    VideoSource,
)
from course_platform.services.reminders import LessonReminderService


class CourseNotFoundError(LookupError):
    """Raised when a requested course does not exist."""


class LessonNotFoundError(LookupError):
    """Raised when a lesson is not part of the requested course."""


@dataclass(frozen=True, slots=True)
class CohortContent:
    cohort_id: UUID
    title: str
    is_active: bool
    students_count: int


@dataclass(frozen=True, slots=True)
class CohortDraft:
    title: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class LessonStageAnalytics:
    position: int
    title: str
    students_count: int


@dataclass(frozen=True, slots=True)
class CohortAnalytics:
    cohort_id: UUID
    title: str
    students_count: int
    active_students: int
    completed_students: int
    average_progress_percent: int
    lesson_stages: tuple[LessonStageAnalytics, ...]


@dataclass(frozen=True, slots=True)
class CourseAnalytics:
    course_id: UUID
    total_students: int
    average_progress_percent: int
    cohorts: tuple[CohortAnalytics, ...]


@dataclass(frozen=True, slots=True)
class AssignmentContent:
    instructions: str
    submission_kind: SubmissionKind
    is_required: bool


@dataclass(frozen=True, slots=True)
class LessonMaterialContent:
    material_id: UUID
    position: int
    title: str
    description: str | None
    kind: str
    video_source: VideoSource
    video_reference: str | None


@dataclass(frozen=True, slots=True)
class LessonContent:
    lesson_id: UUID
    position: int
    title: str
    description: str | None
    video_source: VideoSource
    video_reference: str | None
    materials: tuple[LessonMaterialContent, ...]
    release_offset_hours: int
    requires_view_confirmation: bool
    is_published: bool
    assignment: AssignmentContent | None


@dataclass(frozen=True, slots=True)
class ReminderStepContent:
    sequence: int
    delay_hours: int
    kind: ReminderKind
    message_text: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class ReminderStepDraft:
    delay_hours: int
    kind: ReminderKind
    message_text: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class CourseContent:
    course_id: UUID
    slug: str
    title: str
    description: str | None
    audience: CourseAudience
    unlock_rule: UnlockRule
    is_active: bool
    lessons: tuple[LessonContent, ...]
    reminder_steps: tuple[ReminderStepContent, ...]


@dataclass(frozen=True, slots=True)
class LessonDraft:
    title: str
    description: str | None
    video_source: VideoSource
    video_reference: str | None
    release_offset_hours: int
    requires_view_confirmation: bool
    is_published: bool
    assignment: AssignmentContent | None


class CourseAdminService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, course_id: UUID) -> CourseContent:
        async with self._session_factory() as session:
            course = await session.scalar(
                select(Course)
                .options(
                    selectinload(Course.lessons).selectinload(Lesson.assignment),
                    selectinload(Course.lessons).selectinload(Lesson.materials),
                    selectinload(Course.reminder_steps),
                )
                .where(Course.id == course_id)
            )
            if course is None:
                raise CourseNotFoundError(course_id)
            return self._to_content(course)

    async def update_course(
        self,
        course_id: UUID,
        *,
        title: str,
        description: str | None,
        is_active: bool,
    ) -> CourseContent:
        async with session_scope(self._session_factory) as session:
            course = await session.get(Course, course_id)
            if course is None:
                raise CourseNotFoundError(course_id)
            course.title = title.strip()
            course.description = description.strip() if description else None
            course.is_active = is_active
        return await self.get(course_id)

    async def replace_reminder_steps(
        self,
        course_id: UUID,
        drafts: tuple[ReminderStepDraft, ...],
    ) -> CourseContent:
        async with session_scope(self._session_factory) as session:
            course = await session.scalar(
                select(Course)
                .options(selectinload(Course.reminder_steps))
                .where(Course.id == course_id)
            )
            if course is None:
                raise CourseNotFoundError(course_id)

            existing = sorted(course.reminder_steps, key=lambda item: item.sequence)
            active_step_ids: set[UUID] = set()
            for sequence, draft in enumerate(drafts, start=1):
                if sequence <= len(existing):
                    step = existing[sequence - 1]
                else:
                    step = CourseReminderStep(course_id=course_id, sequence=sequence)
                    session.add(step)
                step.sequence = sequence
                step.delay_hours = draft.delay_hours
                step.kind = draft.kind
                step.message_text = draft.message_text.strip()
                step.is_active = draft.is_active
                await session.flush()
                if step.is_active:
                    active_step_ids.add(step.id)

            for step in existing[len(drafts) :]:
                step.is_active = False

            queued = list(
                await session.execute(
                    select(LessonReminder, CourseReminderStep, LessonProgress)
                    .join(CourseReminderStep, CourseReminderStep.id == LessonReminder.step_id)
                    .join(
                        LessonProgress,
                        (LessonProgress.enrollment_id == LessonReminder.enrollment_id)
                        & (LessonProgress.lesson_id == LessonReminder.lesson_id),
                    )
                    .join(Lesson, Lesson.id == LessonReminder.lesson_id)
                    .where(
                        Lesson.course_id == course_id,
                        LessonReminder.status.in_(
                            [ReminderStatus.PENDING, ReminderStatus.FAILED]
                        ),
                    )
                )
            )
            for reminder, step, progress in queued:
                if step.id not in active_step_ids:
                    reminder.status = ReminderStatus.CANCELLED
                    reminder.last_error = None
                elif progress.available_at is not None:
                    reminder.status = ReminderStatus.PENDING
                    reminder.scheduled_at = progress.available_at + timedelta(
                        hours=step.delay_hours
                    )
                    reminder.attempts = 0
                    reminder.last_error = None

            available_lessons = await session.execute(
                select(Enrollment, Lesson, LessonProgress)
                .join(LessonProgress, LessonProgress.enrollment_id == Enrollment.id)
                .join(Lesson, Lesson.id == LessonProgress.lesson_id)
                .where(
                    Lesson.course_id == course_id,
                    LessonProgress.status == LessonProgressStatus.AVAILABLE,
                    LessonProgress.available_at.is_not(None),
                )
            )
            for enrollment, lesson, progress in available_lessons:
                await LessonReminderService.ensure_scheduled(
                    session,
                    enrollment=enrollment,
                    lesson=lesson,
                    available_at=progress.available_at,
                )

        return await self.get(course_id)

    async def create_course(
        self,
        *,
        title: str,
        description: str | None,
        is_active: bool = True,
        audience: CourseAudience = CourseAudience.TELEGRAM,
        unlock_rule: UnlockRule = UnlockRule.AFTER_ACCEPTANCE,
    ) -> CourseContent:
        async with session_scope(self._session_factory) as session:
            base_title = title.strip()
            if not base_title:
                raise ValueError("title")
            slug_root = self._slugify(base_title)
            slug = slug_root
            suffix = 2
            while await session.scalar(select(Course.id).where(Course.slug == slug)) is not None:
                slug = f"{slug_root}-{suffix}"
                suffix += 1
            course = Course(
                slug=slug,
                title=base_title,
                description=description.strip() if description else None,
                audience=audience,
                is_active=is_active,
                unlock_rule=unlock_rule,
            )
            session.add(course)
            await session.flush()
            if audience is CourseAudience.DISCORD:
                session.add(
                    Cohort(
                        course_id=course.id,
                        title="Основной поток",
                        is_active=True,
                    )
                )
        return await self.get(course.id)

    async def create_lesson(self, course_id: UUID, draft: LessonDraft) -> CourseContent:
        async with session_scope(self._session_factory) as session:
            course = await session.get(Course, course_id)
            if course is None:
                raise CourseNotFoundError(course_id)
            last_position = await session.scalar(
                select(func.max(Lesson.position)).where(Lesson.course_id == course_id)
            )
            lesson = Lesson(course_id=course_id, position=(last_position or 0) + 1)
            self._apply_lesson(lesson, draft)
            session.add(lesson)
        return await self.get(course_id)

    async def copy_lesson(self, course_id: UUID, source_lesson_id: UUID) -> CourseContent:
        async with session_scope(self._session_factory) as session:
            course = await session.get(Course, course_id)
            if course is None:
                raise CourseNotFoundError(course_id)

            source = await session.scalar(
                select(Lesson)
                .options(
                    selectinload(Lesson.assignment),
                    selectinload(Lesson.materials),
                )
                .where(Lesson.id == source_lesson_id)
            )
            if source is None:
                raise LessonNotFoundError(source_lesson_id)

            last_position = await session.scalar(
                select(func.max(Lesson.position)).where(Lesson.course_id == course_id)
            )
            lesson = Lesson(
                course_id=course_id,
                position=(last_position or 0) + 1,
                title=source.title,
                description=source.description,
                video_source=source.video_source,
                video_reference=source.video_reference,
                release_offset_hours=source.release_offset_hours,
                requires_view_confirmation=source.requires_view_confirmation,
                is_published=source.is_published,
            )
            if source.assignment is not None:
                lesson.assignment = Assignment(
                    instructions=source.assignment.instructions,
                    submission_kind=source.assignment.submission_kind,
                    is_required=source.assignment.is_required,
                )
            for material in sorted(source.materials, key=lambda item: item.position):
                lesson.materials.append(
                    LessonMaterial(
                        position=material.position,
                        title=material.title,
                        description=material.description,
                        kind=material.kind,
                        video_source=material.video_source,
                        video_reference=material.video_reference,
                    )
                )
            session.add(lesson)
        return await self.get(course_id)

    async def update_lesson(
        self,
        course_id: UUID,
        lesson_id: UUID,
        draft: LessonDraft,
    ) -> CourseContent:
        async with session_scope(self._session_factory) as session:
            lesson = await session.scalar(
                select(Lesson)
                .options(selectinload(Lesson.assignment))
                .where(Lesson.id == lesson_id, Lesson.course_id == course_id)
            )
            if lesson is None:
                raise LessonNotFoundError(lesson_id)
            self._apply_lesson(lesson, draft)
        return await self.get(course_id)

    async def list_cohorts(self, course_id: UUID) -> tuple[CohortContent, ...]:
        async with self._session_factory() as session:
            course_exists = await session.scalar(
                select(Course.id).where(Course.id == course_id)
            )
            if course_exists is None:
                raise CourseNotFoundError(course_id)

            student_count = (
                select(func.count(distinct(Enrollment.student_id)))
                .where(Enrollment.cohort_id == Cohort.id)
                .correlate(Cohort)
                .scalar_subquery()
            )
            rows = await session.execute(
                select(
                    Cohort.id,
                    Cohort.title,
                    Cohort.is_active,
                    student_count.label("students_count"),
                )
                .where(Cohort.course_id == course_id)
                .order_by(Cohort.created_at.desc())
            )
            return tuple(
                CohortContent(
                    cohort_id=row.id,
                    title=row.title,
                    is_active=row.is_active,
                    students_count=row.students_count,
                )
                for row in rows
            )

    async def analytics(self, course_id: UUID) -> CourseAnalytics:
        async with self._session_factory() as session:
            course = await session.scalar(
                select(Course)
                .options(
                    selectinload(Course.lessons),
                    selectinload(Course.cohorts)
                    .selectinload(Cohort.enrollments)
                    .selectinload(Enrollment.lesson_progress),
                )
                .where(Course.id == course_id)
            )
            if course is None:
                raise CourseNotFoundError(course_id)

            lessons = sorted(course.lessons, key=lambda item: item.position)
            total_lessons = len(lessons)
            cohort_rows: list[CohortAnalytics] = []
            all_progress: list[int] = []
            for cohort in sorted(course.cohorts, key=lambda item: item.title.lower()):
                enrollment_progress: list[int] = []
                for enrollment in cohort.enrollments:
                    completed = sum(
                        progress.status is LessonProgressStatus.COMPLETED
                        for progress in enrollment.lesson_progress
                    )
                    percent = round(completed * 100 / total_lessons) if total_lessons else 0
                    enrollment_progress.append(percent)
                    all_progress.append(percent)

                cohort_rows.append(
                    CohortAnalytics(
                        cohort_id=cohort.id,
                        title=cohort.title,
                        students_count=len(cohort.enrollments),
                        active_students=sum(
                            enrollment.status is EnrollmentStatus.ACTIVE
                            for enrollment in cohort.enrollments
                        ),
                        completed_students=sum(
                            enrollment.status is EnrollmentStatus.COMPLETED
                            for enrollment in cohort.enrollments
                        ),
                        average_progress_percent=(
                            round(sum(enrollment_progress) / len(enrollment_progress))
                            if enrollment_progress
                            else 0
                        ),
                        lesson_stages=tuple(
                            LessonStageAnalytics(
                                position=lesson.position,
                                title=lesson.title,
                                students_count=sum(
                                    enrollment.status is not EnrollmentStatus.COMPLETED
                                    and enrollment.current_lesson_position == lesson.position
                                    for enrollment in cohort.enrollments
                                ),
                            )
                            for lesson in lessons
                        ),
                    )
                )

            return CourseAnalytics(
                course_id=course.id,
                total_students=sum(item.students_count for item in cohort_rows),
                average_progress_percent=(
                    round(sum(all_progress) / len(all_progress)) if all_progress else 0
                ),
                cohorts=tuple(cohort_rows),
            )

    async def create_cohort(self, course_id: UUID, draft: CohortDraft) -> tuple[CohortContent, ...]:
        async with session_scope(self._session_factory) as session:
            course = await session.get(Course, course_id)
            if course is None:
                raise CourseNotFoundError(course_id)
            session.add(
                Cohort(
                    course_id=course_id,
                    title=draft.title.strip(),
                    is_active=draft.is_active,
                )
            )
        return await self.list_cohorts(course_id)

    async def update_cohort(
        self,
        course_id: UUID,
        cohort_id: UUID,
        draft: CohortDraft,
    ) -> tuple[CohortContent, ...]:
        async with session_scope(self._session_factory) as session:
            cohort = await session.scalar(
                select(Cohort).where(
                    Cohort.id == cohort_id,
                    Cohort.course_id == course_id,
                )
            )
            if cohort is None:
                raise CourseNotFoundError(course_id)
            cohort.title = draft.title.strip()
            cohort.is_active = draft.is_active
        return await self.list_cohorts(course_id)

    @staticmethod
    def _apply_lesson(lesson: Lesson, draft: LessonDraft) -> None:
        lesson.title = draft.title.strip()
        lesson.description = draft.description.strip() if draft.description else None
        lesson.video_source = draft.video_source
        lesson.video_reference = draft.video_reference.strip() if draft.video_reference else None
        lesson.release_offset_hours = draft.release_offset_hours
        lesson.requires_view_confirmation = draft.requires_view_confirmation
        lesson.is_published = draft.is_published
        if draft.assignment is not None:
            if lesson.assignment is None:
                lesson.assignment = Assignment(instructions=draft.assignment.instructions.strip())
            lesson.assignment.instructions = draft.assignment.instructions.strip()
            lesson.assignment.submission_kind = draft.assignment.submission_kind
            lesson.assignment.is_required = draft.assignment.is_required

    @staticmethod
    def _slugify(value: str) -> str:
        slug = []
        previous_dash = False
        for char in value.lower():
            if char.isalnum():
                slug.append(char)
                previous_dash = False
            elif not previous_dash:
                slug.append("-")
                previous_dash = True
        result = "".join(slug).strip("-")
        return result or "course"

    @classmethod
    def _to_content(cls, course: Course) -> CourseContent:
        return CourseContent(
            course_id=course.id,
            slug=course.slug,
            title=course.title,
            description=course.description,
            audience=course.audience,
            unlock_rule=course.unlock_rule,
            is_active=course.is_active,
            lessons=tuple(
                LessonContent(
                    lesson_id=lesson.id,
                    position=lesson.position,
                    title=lesson.title,
                    description=lesson.description,
                    video_source=lesson.video_source,
                    video_reference=lesson.video_reference,
                    materials=tuple(
                        LessonMaterialContent(
                            material_id=material.id,
                            position=material.position,
                            title=material.title,
                            description=material.description,
                            kind=material.kind,
                            video_source=material.video_source,
                            video_reference=material.video_reference,
                        )
                        for material in sorted(
                            lesson.materials, key=lambda item: item.position
                        )
                    ),
                    release_offset_hours=lesson.release_offset_hours,
                    requires_view_confirmation=lesson.requires_view_confirmation,
                    is_published=lesson.is_published,
                    assignment=(
                        AssignmentContent(
                            instructions=lesson.assignment.instructions,
                            submission_kind=lesson.assignment.submission_kind,
                            is_required=lesson.assignment.is_required,
                        )
                        if lesson.assignment is not None
                        else None
                    ),
                )
                for lesson in sorted(course.lessons, key=lambda item: item.position)
            ),
            reminder_steps=tuple(
                ReminderStepContent(
                    sequence=step.sequence,
                    delay_hours=step.delay_hours,
                    kind=step.kind,
                    message_text=step.message_text,
                    is_active=step.is_active,
                )
                for step in sorted(course.reminder_steps, key=lambda item: item.sequence)
                if step.is_active
            ),
        )
