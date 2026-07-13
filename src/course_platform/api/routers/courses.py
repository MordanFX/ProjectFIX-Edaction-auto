"""Course overview and authenticated course content management."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from course_platform.api.dependencies import (
    AdminDashboardServiceDependency,
    CourseAdminServiceDependency,
    CurrentStaffDependency,
    SessionDependency,
)
from course_platform.api.schemas import (
    CohortResponse,
    CohortWriteRequest,
    CourseAnalyticsResponse,
    CourseContentResponse,
    CourseCreateRequest,
    CourseOverviewResponse,
    CourseUpdateRequest,
    LessonCopyRequest,
    LessonCoverResponse,
    LessonWriteRequest,
    ReminderStepsWriteRequest,
)
from course_platform.integrations.vimeo import VimeoOEmbedClient
from course_platform.models import Lesson
from course_platform.models.enums import VideoSource
from course_platform.services.course_admin import (
    AssignmentContent,
    CohortDraft,
    CourseNotFoundError,
    LessonDraft,
    LessonNotFoundError,
    ReminderStepDraft,
)

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseOverviewResponse])
async def courses_overview(
    staff: CurrentStaffDependency,
    dashboard: AdminDashboardServiceDependency,
) -> list[CourseOverviewResponse]:
    del staff
    return [
        CourseOverviewResponse.from_domain(item)
        for item in await dashboard.list_courses()
    ]


@router.post("", response_model=CourseContentResponse)
async def create_course(
    payload: CourseCreateRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        return CourseContentResponse.from_domain(
            await courses.create_course(**payload.model_dump())
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course title is required",
        ) from None


@router.get("/{course_id}", response_model=CourseContentResponse)
async def course_content(
    course_id: UUID,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        return CourseContentResponse.from_domain(await courses.get(course_id))
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


@router.get("/lessons/{lesson_id}/cover", response_model=LessonCoverResponse)
async def lesson_cover(
    lesson_id: UUID,
    request: Request,
    staff: CurrentStaffDependency,
    session: SessionDependency,
) -> LessonCoverResponse:
    del staff
    lesson = await session.scalar(
        select(Lesson)
        .options(selectinload(Lesson.materials))
        .where(Lesson.id == lesson_id)
    )
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        )

    image_url = _lesson_image_cover_url(lesson)
    if image_url is not None:
        return LessonCoverResponse(cover_url=image_url, source="image")

    if lesson.video_source is VideoSource.EXTERNAL_URL and lesson.video_reference:
        async with VimeoOEmbedClient(
            transport=request.app.state.vimeo_transport,
        ) as vimeo:
            metadata = await vimeo.get_metadata(lesson.video_reference)
        if metadata is not None:
            return LessonCoverResponse(cover_url=metadata.thumbnail_url, source="vimeo")

    return LessonCoverResponse(cover_url=None, source=None)


@router.get("/{course_id}/analytics", response_model=CourseAnalyticsResponse)
async def course_analytics(
    course_id: UUID,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseAnalyticsResponse:
    del staff
    try:
        return CourseAnalyticsResponse.from_domain(await courses.analytics(course_id))
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


@router.get("/{course_id}/cohorts", response_model=list[CohortResponse])
async def course_cohorts(
    course_id: UUID,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> list[CohortResponse]:
    del staff
    try:
        return [CohortResponse(**asdict(item)) for item in await courses.list_cohorts(course_id)]
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


@router.post("/{course_id}/cohorts", response_model=list[CohortResponse])
async def create_cohort(
    course_id: UUID,
    payload: CohortWriteRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> list[CohortResponse]:
    del staff
    try:
        return [
            CohortResponse(**asdict(item))
            for item in await courses.create_cohort(
                course_id,
                CohortDraft(**payload.model_dump()),
            )
        ]
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


@router.patch("/{course_id}/cohorts/{cohort_id}", response_model=list[CohortResponse])
async def update_cohort(
    course_id: UUID,
    cohort_id: UUID,
    payload: CohortWriteRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> list[CohortResponse]:
    del staff
    try:
        return [
            CohortResponse(**asdict(item))
            for item in await courses.update_cohort(
                course_id,
                cohort_id,
                CohortDraft(**payload.model_dump()),
            )
        ]
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cohort not found",
        ) from None


def _lesson_image_cover_url(lesson: Lesson) -> str | None:
    for material in sorted(lesson.materials, key=lambda item: item.position):
        if material.kind != "image" or not material.video_reference:
            continue
        reference = material.video_reference.strip()
        if reference.startswith(("https://", "http://", "/")):
            return reference
        public_prefix = "frontend/public/"
        if reference.startswith(public_prefix):
            return f"/{reference.removeprefix(public_prefix)}"
        return f"/{reference}"
    return None


@router.patch("/{course_id}", response_model=CourseContentResponse)
async def update_course(
    course_id: UUID,
    payload: CourseUpdateRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        content = await courses.update_course(course_id, **payload.model_dump())
        return CourseContentResponse.from_domain(content)
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


@router.put("/{course_id}/reminder-steps", response_model=CourseContentResponse)
async def replace_reminder_steps(
    course_id: UUID,
    payload: ReminderStepsWriteRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        return CourseContentResponse.from_domain(
            await courses.replace_reminder_steps(
                course_id,
                tuple(ReminderStepDraft(**step.model_dump()) for step in payload.steps),
            )
        )
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


def _lesson_draft(payload: LessonWriteRequest) -> LessonDraft:
    assignment = (
        AssignmentContent(**payload.assignment.model_dump())
        if payload.assignment is not None
        else None
    )
    return LessonDraft(**payload.model_dump(exclude={"assignment"}), assignment=assignment)


@router.post("/{course_id}/lessons", response_model=CourseContentResponse)
async def create_lesson(
    course_id: UUID,
    payload: LessonWriteRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        return CourseContentResponse.from_domain(
            await courses.create_lesson(course_id, _lesson_draft(payload))
        )
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None


@router.post("/{course_id}/lessons/from-knowledge", response_model=CourseContentResponse)
async def copy_lesson_from_knowledge(
    course_id: UUID,
    payload: LessonCopyRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        return CourseContentResponse.from_domain(
            await courses.copy_lesson(course_id, payload.source_lesson_id)
        )
    except CourseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        ) from None
    except LessonNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        ) from None


@router.patch("/{course_id}/lessons/{lesson_id}", response_model=CourseContentResponse)
async def update_lesson(
    course_id: UUID,
    lesson_id: UUID,
    payload: LessonWriteRequest,
    staff: CurrentStaffDependency,
    courses: CourseAdminServiceDependency,
) -> CourseContentResponse:
    del staff
    try:
        return CourseContentResponse.from_domain(
            await courses.update_lesson(course_id, lesson_id, _lesson_draft(payload))
        )
    except (CourseNotFoundError, LessonNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
        ) from None
