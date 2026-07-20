"""Read-only student overview and progress details for curators."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from course_platform.api.dependencies import (
    AdminDashboardServiceDependency,
    CurrentAdminDependency,
    CurrentStaffDependency,
    StudentAccessServiceDependency,
)
from course_platform.api.schemas import (
    StudentAccessUpdateRequest,
    StudentAccessUpdateResponse,
    StudentCuratorAssignRequest,
    StudentDetailResponse,
    StudentLessonDetailResponse,
    StudentOverviewResponse,
)
from course_platform.models.enums import StaffRole
from course_platform.models.staff import StaffUser
from course_platform.services.access_scope import StaffScope
from course_platform.services.admin_dashboard import (
    CuratorNotFoundError,
    StudentLessonNotFoundError,
    StudentNotFoundError,
)
from course_platform.services.students import StudentAccessError

router = APIRouter(prefix="/students", tags=["students"])


def _scope(staff: StaffUser) -> StaffScope:
    return StaffScope(staff_id=staff.id, is_admin=staff.role is StaffRole.ADMIN)


@router.get("", response_model=list[StudentOverviewResponse])
async def students_overview(
    staff: CurrentStaffDependency,
    dashboard: AdminDashboardServiceDependency,
) -> list[StudentOverviewResponse]:
    return [
        StudentOverviewResponse.from_domain(item)
        for item in await dashboard.list_students(viewer=_scope(staff))
    ]


@router.get("/{student_id}", response_model=StudentDetailResponse)
async def student_detail(
    student_id: UUID,
    staff: CurrentStaffDependency,
    dashboard: AdminDashboardServiceDependency,
    enrollment_id: UUID | None = None,
) -> StudentDetailResponse:
    try:
        detail = await dashboard.get_student_detail(
            student_id=student_id,
            enrollment_id=enrollment_id,
            viewer=_scope(staff),
        )
    except StudentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student or enrollment not found",
        ) from None
    return StudentDetailResponse.from_domain(detail)


@router.get(
    "/{student_id}/lessons/{lesson_id}",
    response_model=StudentLessonDetailResponse,
)
async def student_lesson_detail(
    student_id: UUID,
    lesson_id: UUID,
    enrollment_id: UUID,
    staff: CurrentStaffDependency,
    dashboard: AdminDashboardServiceDependency,
) -> StudentLessonDetailResponse:
    try:
        return StudentLessonDetailResponse.from_domain(
            await dashboard.get_student_lesson_detail(
                student_id=student_id,
                enrollment_id=enrollment_id,
                lesson_id=lesson_id,
                viewer=_scope(staff),
            )
        )
    except StudentLessonNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student lesson not found",
        ) from None


@router.patch("/{student_id}/access", response_model=StudentAccessUpdateResponse)
async def update_student_access(
    student_id: UUID,
    payload: StudentAccessUpdateRequest,
    staff: CurrentStaffDependency,
    access: StudentAccessServiceDependency,
) -> StudentAccessUpdateResponse:
    del staff
    try:
        detail = await access.update_enrollment(
            student_id=student_id,
            cohort_id=payload.cohort_id,
            status=payload.status,
            access_type=payload.access_type,
            current_lesson_position=payload.current_lesson_position,
        )
    except StudentAccessError as error:
        detail_code = str(error)
        if detail_code == "student-not-found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Student not found",
            ) from None
        if detail_code == "cohort-not-found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cohort not found",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to update student access",
        ) from None
    return StudentAccessUpdateResponse.from_domain(detail)


@router.patch("/{student_id}/curator", response_model=StudentDetailResponse)
async def assign_student_curator(
    student_id: UUID,
    payload: StudentCuratorAssignRequest,
    admin: CurrentAdminDependency,
    dashboard: AdminDashboardServiceDependency,
) -> StudentDetailResponse:
    del admin
    try:
        detail = await dashboard.assign_curator(
            student_id=student_id,
            curator_id=payload.curator_id,
        )
    except StudentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram student not found",
        ) from None
    except CuratorNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curator not found or inactive",
        ) from None
    return StudentDetailResponse.from_domain(detail)


@router.delete("/{student_id}")
async def delete_telegram_student(
    student_id: UUID,
    admin: CurrentAdminDependency,
    access: StudentAccessServiceDependency,
) -> dict[str, bool]:
    del admin
    try:
        await access.delete_telegram_student(student_id=student_id)
    except StudentAccessError as error:
        detail_code = str(error)
        if detail_code == "telegram-student-not-found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Telegram student not found",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to delete Telegram student",
        ) from None
    return {"deleted": True}
