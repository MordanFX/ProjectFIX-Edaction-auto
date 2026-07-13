"""Curator-facing Discord workspace endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from course_platform.api.dependencies import (
    CurrentStaffDependency,
    DiscordAccessServiceDependency,
    DiscordDashboardServiceDependency,
    DiscordLessonDeliveryServiceDependency,
    DiscordQuestionServiceDependency,
    SettingsDependency,
    StudentAccessServiceDependency,
)
from course_platform.api.schemas import (
    DiscordAccessExtendRequest,
    DiscordAccessResponse,
    DiscordAccessSetExpiryRequest,
    DiscordCourseAssignmentRequest,
    DiscordLessonDispatchCreateRequest,
    DiscordLessonDispatchResponse,
    DiscordQuestionResponse,
    DiscordWorkspaceOverviewResponse,
)
from course_platform.services.discord_access import DiscordAccessError
from course_platform.services.discord_lesson_deliveries import DiscordLessonDispatchError
from course_platform.services.students import StudentAccessError

router = APIRouter(prefix="/discord", tags=["discord"])


@router.get("/accesses", response_model=list[DiscordAccessResponse])
async def discord_accesses(
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    access: DiscordAccessServiceDependency,
) -> list[DiscordAccessResponse]:
    del staff
    return [
        DiscordAccessResponse.from_domain(item)
        for item in await access.list_accesses(guild_id=settings.discord_guild_id)
    ]


@router.post("/accesses/{student_id}/extend", response_model=DiscordAccessResponse)
async def extend_discord_access(
    student_id: UUID,
    payload: DiscordAccessExtendRequest,
    staff: CurrentStaffDependency,
    access: DiscordAccessServiceDependency,
) -> DiscordAccessResponse:
    del staff
    try:
        item = await access.extend_access(student_id=student_id, months=payload.months)
    except DiscordAccessError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    return DiscordAccessResponse.from_domain(item)


@router.post("/accesses/{student_id}/expiry", response_model=DiscordAccessResponse)
async def set_discord_access_expiry(
    student_id: UUID,
    payload: DiscordAccessSetExpiryRequest,
    staff: CurrentStaffDependency,
    access: DiscordAccessServiceDependency,
) -> DiscordAccessResponse:
    del staff
    try:
        item = await access.set_expiry(
            student_id=student_id,
            expires_at=payload.access_expires_at,
        )
    except DiscordAccessError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    return DiscordAccessResponse.from_domain(item)


@router.post("/accesses/{student_id}/close", response_model=DiscordAccessResponse)
async def close_discord_access(
    student_id: UUID,
    staff: CurrentStaffDependency,
    access: DiscordAccessServiceDependency,
) -> DiscordAccessResponse:
    del staff
    try:
        item = await access.close_access(student_id=student_id)
    except DiscordAccessError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    return DiscordAccessResponse.from_domain(item)


@router.get("/questions", response_model=list[DiscordQuestionResponse])
async def discord_questions(
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    questions: DiscordQuestionServiceDependency,
    include_resolved: bool = True,
) -> list[DiscordQuestionResponse]:
    del staff
    return [
        DiscordQuestionResponse.from_domain(item)
        for item in await questions.list_questions(
            guild_id=settings.discord_guild_id,
            include_resolved=include_resolved,
        )
    ]


@router.post("/questions/{question_id}/resolve", response_model=DiscordQuestionResponse)
async def resolve_discord_question(
    question_id: UUID,
    staff: CurrentStaffDependency,
    questions: DiscordQuestionServiceDependency,
) -> DiscordQuestionResponse:
    item = await questions.resolve_question(question_id=question_id, staff_id=staff.id)
    if item is None:
        raise HTTPException(status_code=404, detail="discord-question-not-found")
    return DiscordQuestionResponse.from_domain(item)


@router.get("/lesson-dispatches", response_model=list[DiscordLessonDispatchResponse])
async def lesson_dispatches(
    staff: CurrentStaffDependency,
    deliveries: DiscordLessonDeliveryServiceDependency,
) -> list[DiscordLessonDispatchResponse]:
    del staff
    return [
        DiscordLessonDispatchResponse.from_domain(item)
        for item in await deliveries.list_dispatches()
    ]


@router.post("/lesson-dispatches", response_model=DiscordLessonDispatchResponse)
async def create_lesson_dispatch(
    payload: DiscordLessonDispatchCreateRequest,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    deliveries: DiscordLessonDeliveryServiceDependency,
) -> DiscordLessonDispatchResponse:
    if settings.discord_guild_id is None:
        raise HTTPException(status_code=400, detail="discord-guild-not-configured")
    try:
        result = await deliveries.create_dispatch(
            guild_id=settings.discord_guild_id,
            lesson_id=payload.lesson_id,
            student_ids=tuple(payload.student_ids),
            custom_message=payload.custom_message,
            staff_id=staff.id,
        )
    except DiscordLessonDispatchError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    return DiscordLessonDispatchResponse.from_domain(result)


@router.get("/overview", response_model=DiscordWorkspaceOverviewResponse)
async def discord_overview(
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    dashboard: DiscordDashboardServiceDependency,
) -> DiscordWorkspaceOverviewResponse:
    del staff
    return DiscordWorkspaceOverviewResponse.from_domain(
        await dashboard.overview(
            settings.discord_guild_id,
            submissions_enabled=settings.discord_message_content_enabled,
        )
    )


@router.patch(
    "/participants/{student_id}/course",
    response_model=DiscordWorkspaceOverviewResponse,
)
async def update_discord_access(
    student_id: UUID,
    payload: DiscordCourseAssignmentRequest,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    access: StudentAccessServiceDependency,
    dashboard: DiscordDashboardServiceDependency,
) -> DiscordWorkspaceOverviewResponse:
    del staff
    try:
        await access.assign_discord_course(
            student_id=student_id,
            course_id=payload.course_id,
        )
    except StudentAccessError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    return DiscordWorkspaceOverviewResponse.from_domain(
        await dashboard.overview(
            settings.discord_guild_id,
            submissions_enabled=settings.discord_message_content_enabled,
        )
    )


@router.delete(
    "/participants/{student_id}/access",
    response_model=DiscordWorkspaceOverviewResponse,
)
async def revoke_discord_access(
    student_id: UUID,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    access: StudentAccessServiceDependency,
    dashboard: DiscordDashboardServiceDependency,
) -> DiscordWorkspaceOverviewResponse:
    del staff
    try:
        await access.revoke_discord_access(student_id=student_id)
    except StudentAccessError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    return DiscordWorkspaceOverviewResponse.from_domain(
        await dashboard.overview(
            settings.discord_guild_id,
            submissions_enabled=settings.discord_message_content_enabled,
        )
    )
