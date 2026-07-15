"""FastAPI dependencies backed by application state."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from course_platform.api.security import (
    InvalidAccessTokenError,
    JWTConfigurationError,
    decode_access_token,
)
from course_platform.config import Settings
from course_platform.models import StaffUser
from course_platform.models.enums import StaffRole
from course_platform.services.admin_dashboard import AdminDashboardService
from course_platform.services.course_admin import CourseAdminService
from course_platform.services.discord_access import DiscordAccessService
from course_platform.services.discord_dashboard import DiscordDashboardService
from course_platform.services.discord_invites import DiscordInviteService
from course_platform.services.discord_lesson_deliveries import DiscordLessonDeliveryService
from course_platform.services.discord_questions import DiscordQuestionService
from course_platform.services.reviews import ReviewService
from course_platform.services.students import StudentAccessService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def get_api_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory(request)
    async with session_factory() as session:
        yield session


def get_review_service(request: Request) -> ReviewService:
    return ReviewService(get_session_factory(request))


def get_admin_dashboard_service(request: Request) -> AdminDashboardService:
    return AdminDashboardService(get_session_factory(request))


def get_course_admin_service(request: Request) -> CourseAdminService:
    return CourseAdminService(get_session_factory(request))


def get_student_access_service(request: Request) -> StudentAccessService:
    return StudentAccessService(get_session_factory(request))


def get_discord_dashboard_service(request: Request) -> DiscordDashboardService:
    return DiscordDashboardService(get_session_factory(request))


def get_discord_access_service(request: Request) -> DiscordAccessService:
    return DiscordAccessService(get_session_factory(request))


def get_discord_invite_service(request: Request) -> DiscordInviteService:
    return DiscordInviteService(get_session_factory(request))


def get_discord_lesson_delivery_service(request: Request) -> DiscordLessonDeliveryService:
    return DiscordLessonDeliveryService(get_session_factory(request))


def get_discord_question_service(request: Request) -> DiscordQuestionService:
    return DiscordQuestionService(get_session_factory(request))


async def get_current_staff(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_api_settings)],
) -> StaffUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        claims = decode_access_token(token, settings)
    except (InvalidAccessTokenError, JWTConfigurationError):
        raise unauthorized from None

    staff = await session.get(StaffUser, claims.staff_id)
    if staff is None or not staff.is_active:
        raise unauthorized
    return staff


async def get_current_admin(
    staff: Annotated[StaffUser, Depends(get_current_staff)],
) -> StaffUser:
    if staff.role != StaffRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        )
    return staff


SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_api_settings)]
CurrentStaffDependency = Annotated[StaffUser, Depends(get_current_staff)]
CurrentAdminDependency = Annotated[StaffUser, Depends(get_current_admin)]
ReviewServiceDependency = Annotated[ReviewService, Depends(get_review_service)]
AdminDashboardServiceDependency = Annotated[
    AdminDashboardService, Depends(get_admin_dashboard_service)
]
CourseAdminServiceDependency = Annotated[CourseAdminService, Depends(get_course_admin_service)]
StudentAccessServiceDependency = Annotated[
    StudentAccessService, Depends(get_student_access_service)
]
DiscordDashboardServiceDependency = Annotated[
    DiscordDashboardService, Depends(get_discord_dashboard_service)
]
DiscordAccessServiceDependency = Annotated[
    DiscordAccessService, Depends(get_discord_access_service)
]
DiscordInviteServiceDependency = Annotated[
    DiscordInviteService, Depends(get_discord_invite_service)
]
DiscordLessonDeliveryServiceDependency = Annotated[
    DiscordLessonDeliveryService, Depends(get_discord_lesson_delivery_service)
]
DiscordQuestionServiceDependency = Annotated[
    DiscordQuestionService, Depends(get_discord_question_service)
]
