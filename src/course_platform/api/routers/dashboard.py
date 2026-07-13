"""Curator dashboard summary endpoint."""

from fastapi import APIRouter

from course_platform.api.dependencies import (
    AdminDashboardServiceDependency,
    CurrentStaffDependency,
)
from course_platform.api.schemas import DashboardSummaryResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def dashboard_summary(
    staff: CurrentStaffDependency,
    dashboard: AdminDashboardServiceDependency,
) -> DashboardSummaryResponse:
    del staff
    return DashboardSummaryResponse.from_domain(await dashboard.summary())
