"""Curator dashboard summary endpoint."""

from fastapi import APIRouter

from course_platform.api.dependencies import (
    AdminDashboardServiceDependency,
    CurrentStaffDependency,
)
from course_platform.api.schemas import DashboardSummaryResponse
from course_platform.models.enums import StaffRole
from course_platform.models.staff import StaffUser
from course_platform.services.access_scope import StaffScope

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _scope(staff: StaffUser) -> StaffScope:
    return StaffScope(staff_id=staff.id, is_admin=staff.role is StaffRole.ADMIN)


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    staff: CurrentStaffDependency,
    dashboard: AdminDashboardServiceDependency,
) -> DashboardSummaryResponse:
    return DashboardSummaryResponse.from_domain(await dashboard.summary(viewer=_scope(staff)))
