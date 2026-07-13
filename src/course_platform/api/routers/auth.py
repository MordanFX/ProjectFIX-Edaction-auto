"""Curator login and identity endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from course_platform.api.dependencies import (
    CurrentStaffDependency,
    SessionDependency,
    SettingsDependency,
)
from course_platform.api.schemas import StaffResponse, TokenResponse
from course_platform.api.security import (
    JWTConfigurationError,
    create_access_token,
    verify_password,
)
from course_platform.models import StaffUser

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDependency,
    settings: SettingsDependency,
) -> TokenResponse:
    staff = await session.scalar(select(StaffUser).where(StaffUser.login == form.username))
    if (
        staff is None
        or not staff.is_active
        or staff.password_hash is None
        or not verify_password(form.password, staff.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect login or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        access_token = create_access_token(
            staff_id=staff.id,
            role=staff.role,
            settings=settings,
        )
    except JWTConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from None

    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=StaffResponse)
async def me(staff: CurrentStaffDependency) -> StaffResponse:
    return StaffResponse(
        id=staff.id,
        login=staff.login,
        display_name=staff.display_name,
        role=staff.role,
    )
