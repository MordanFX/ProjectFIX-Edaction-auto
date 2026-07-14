"""Administrator-facing staff management endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from course_platform.api.dependencies import CurrentAdminDependency, SessionDependency
from course_platform.api.schemas import (
    StaffCreateRequest,
    StaffMemberResponse,
    StaffUpdateRequest,
)
from course_platform.api.security import hash_password
from course_platform.models import Feedback, StaffUser, Submission
from course_platform.models.enums import FeedbackVerdict, SubmissionStatus

router = APIRouter(prefix="/staff", tags=["staff"])


@router.get("", response_model=list[StaffMemberResponse])
async def list_staff(
    admin: CurrentAdminDependency,
    session: SessionDependency,
) -> list[StaffMemberResponse]:
    del admin
    result = await session.scalars(
        select(StaffUser).order_by(StaffUser.created_at.desc(), StaffUser.login.asc())
    )
    return [await _staff_response(session, staff) for staff in result]


@router.post("", response_model=StaffMemberResponse, status_code=status.HTTP_201_CREATED)
async def create_staff(
    payload: StaffCreateRequest,
    admin: CurrentAdminDependency,
    session: SessionDependency,
) -> StaffMemberResponse:
    del admin
    staff = StaffUser(
        login=payload.login.strip(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        telegram_user_id=payload.telegram_user_id,
        role=payload.role,
        is_active=payload.is_active,
    )
    session.add(staff)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Staff login or Telegram ID already exists",
        ) from None
    await session.refresh(staff)
    return await _staff_response(session, staff)


@router.patch("/{staff_id}", response_model=StaffMemberResponse)
async def update_staff(
    staff_id: UUID,
    payload: StaffUpdateRequest,
    admin: CurrentAdminDependency,
    session: SessionDependency,
) -> StaffMemberResponse:
    staff = await session.get(StaffUser, staff_id)
    if staff is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Staff member not found",
        )
    if staff.id == admin.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    staff.display_name = payload.display_name.strip()
    staff.role = payload.role
    staff.telegram_user_id = payload.telegram_user_id
    staff.is_active = payload.is_active
    if payload.password:
        staff.password_hash = hash_password(payload.password)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Staff Telegram ID already exists",
        ) from None
    await session.refresh(staff)
    return await _staff_response(session, staff)


async def _staff_response(session: AsyncSession, staff: StaffUser) -> StaffMemberResponse:
    pending_assigned = await session.scalar(
        select(func.count(Submission.id)).where(
            Submission.assigned_reviewer_id == staff.id,
            Submission.status.in_([SubmissionStatus.SUBMITTED, SubmissionStatus.IN_REVIEW]),
        )
    )
    reviewed_total = await session.scalar(
        select(func.count(Feedback.id)).where(Feedback.reviewer_id == staff.id)
    )
    accepted_total = await session.scalar(
        select(func.count(Feedback.id)).where(
            Feedback.reviewer_id == staff.id,
            Feedback.verdict == FeedbackVerdict.ACCEPTED,
        )
    )
    revision_total = await session.scalar(
        select(func.count(Feedback.id)).where(
            Feedback.reviewer_id == staff.id,
            Feedback.verdict == FeedbackVerdict.REVISION_REQUESTED,
        )
    )
    return StaffMemberResponse(
        id=staff.id,
        login=staff.login,
        display_name=staff.display_name,
        role=staff.role,
        telegram_user_id=staff.telegram_user_id,
        is_active=staff.is_active,
        created_at=staff.created_at,
        pending_assigned=pending_assigned or 0,
        reviewed_total=reviewed_total or 0,
        accepted_total=accepted_total or 0,
        revision_total=revision_total or 0,
    )
