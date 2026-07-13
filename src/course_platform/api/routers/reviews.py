"""Protected review queue and attachment media endpoints."""

from asyncio import to_thread
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from course_platform.api.dependencies import (
    CurrentStaffDependency,
    ReviewServiceDependency,
    SettingsDependency,
)
from course_platform.api.schemas import (
    AttachmentPlaybackResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewDetailResponse,
    ReviewQueueItemResponse,
)
from course_platform.api.security import (
    InvalidAccessTokenError,
    JWTConfigurationError,
    create_attachment_media_token,
    decode_attachment_media_token,
)
from course_platform.bot.api import TelegramAPIError, TelegramBotClient, TelegramTransportError
from course_platform.models.enums import SubmissionSource
from course_platform.services.reviews import (
    AttachmentNotFoundError,
    EmptyFeedbackError,
    SubmissionAlreadyReviewedError,
    SubmissionNotFoundError,
    UnauthorizedReviewerError,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])
PLAYBACK_TOKEN_TTL_SECONDS = 1800


@router.get("", response_model=list[ReviewQueueItemResponse])
async def review_queue(
    staff: CurrentStaffDependency,
    reviews: ReviewServiceDependency,
    source: SubmissionSource | None = None,
) -> list[ReviewQueueItemResponse]:
    del staff
    items = await reviews.list_pending(include_reviewed=True, source=source)
    return [ReviewQueueItemResponse.from_domain(item) for item in items]


@router.get("/{submission_id}", response_model=ReviewDetailResponse)
async def review_detail(
    submission_id: UUID,
    staff: CurrentStaffDependency,
    reviews: ReviewServiceDependency,
) -> ReviewDetailResponse:
    del staff
    try:
        item = await reviews.get_detail(submission_id)
    except SubmissionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        ) from None
    return ReviewDetailResponse.from_domain(item)


@router.post(
    "/{submission_id}/attachments/{attachment_id}/playback",
    response_model=AttachmentPlaybackResponse,
)
async def create_attachment_playback(
    submission_id: UUID,
    attachment_id: UUID,
    request: Request,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    reviews: ReviewServiceDependency,
) -> AttachmentPlaybackResponse:
    try:
        media_source = await reviews.get_attachment_media_source(
            submission_id=submission_id,
            attachment_id=attachment_id,
        )
        token = create_attachment_media_token(
            staff_id=staff.id,
            submission_id=submission_id,
            attachment_id=attachment_id,
            settings=settings,
            expires_in_seconds=PLAYBACK_TOKEN_TTL_SECONDS,
        )
    except AttachmentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        ) from None
    except JWTConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media playback is not configured",
        ) from None

    if media_source.external_url is not None:
        return AttachmentPlaybackResponse(
            url=media_source.external_url,
            expires_in=300,
        )

    media_url = request.url_for(
        "stream_review_attachment",
        submission_id=str(submission_id),
        attachment_id=str(attachment_id),
    )
    return AttachmentPlaybackResponse(
        url=f"{media_url.path}?token={quote(token)}",
        expires_in=PLAYBACK_TOKEN_TTL_SECONDS,
    )


@router.get(
    "/{submission_id}/attachments/{attachment_id}/media",
    name="stream_review_attachment",
    response_model=None,
)
async def stream_review_attachment(
    submission_id: UUID,
    attachment_id: UUID,
    token: str,
    request: Request,
    settings: SettingsDependency,
    reviews: ReviewServiceDependency,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> FileResponse | StreamingResponse:
    try:
        claims = decode_attachment_media_token(token, settings)
    except (InvalidAccessTokenError, JWTConfigurationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired media token",
        ) from None
    if claims.submission_id != submission_id or claims.attachment_id != attachment_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Media token mismatch")

    try:
        source = await reviews.get_attachment_media_source(
            submission_id=submission_id,
            attachment_id=attachment_id,
        )
    except AttachmentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        ) from None

    if settings.telegram_bot_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram bot token is not configured",
        )
    if source.telegram_file_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Telegram attachment source is unavailable",
        )

    telegram = TelegramBotClient(
        settings.telegram_bot_token,
        api_url=settings.telegram_api_url,
        transport=request.app.state.telegram_transport,
    )
    try:
        telegram_file = await telegram.get_file(source.telegram_file_id)
        if not telegram_file.file_path:
            raise TelegramTransportError("Telegram did not provide a file path")

        local_path = Path(telegram_file.file_path)
        if local_path.is_absolute() and await to_thread(local_path.is_file):
            await telegram.close()
            return FileResponse(
                local_path,
                media_type=source.mime_type or "application/octet-stream",
                filename=source.file_name,
                content_disposition_type="inline",
            )

        upstream = await telegram.open_file(
            telegram_file.file_path,
            range_header=range_header,
        )
    except TelegramAPIError as error:
        await telegram.close()
        is_cloud_size_limit = error.error_code == 400 and (source.file_size or 0) > 20_000_000
        raise HTTPException(
            status_code=(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                if is_cloud_size_limit
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail=(
                "This file exceeds the cloud Telegram Bot API download limit"
                if is_cloud_size_limit
                else "Telegram could not prepare this file"
            ),
        ) from None
    except TelegramTransportError:
        await telegram.close()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram file service is temporarily unavailable",
        ) from None

    if upstream.status_code not in {status.HTTP_200_OK, status.HTTP_206_PARTIAL_CONTENT}:
        upstream_status = upstream.status_code
        await upstream.aclose()
        await telegram.close()
        if upstream_status == status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE:
            raise HTTPException(
                status_code=upstream_status,
                detail="Requested range is unavailable",
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram file download failed",
        )

    response_headers = {
        key: value
        for key in ("content-length", "content-range", "accept-ranges", "etag", "last-modified")
        if (value := upstream.headers.get(key)) is not None
    }
    response_headers["Cache-Control"] = "private, no-store"
    if source.file_name:
        response_headers["Content-Disposition"] = (
            f"inline; filename*=UTF-8''{quote(source.file_name)}"
        )

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await telegram.close()

    return StreamingResponse(
        body(),
        status_code=upstream.status_code,
        media_type=source.mime_type or upstream.headers.get("content-type"),
        headers=response_headers,
    )


@router.post("/{submission_id}/decision", response_model=ReviewDecisionResponse)
async def decide_review(
    submission_id: UUID,
    decision: ReviewDecisionRequest,
    staff: CurrentStaffDependency,
    reviews: ReviewServiceDependency,
) -> ReviewDecisionResponse:
    try:
        result = await reviews.review_by_staff_id(
            submission_id=submission_id,
            reviewer_id=staff.id,
            verdict=decision.verdict,
            message=decision.message,
        )
    except SubmissionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        ) from None
    except SubmissionAlreadyReviewedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission is already reviewed",
        ) from None
    except EmptyFeedbackError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Feedback message must not be empty",
        ) from None
    except UnauthorizedReviewerError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer is inactive",
        ) from None

    return ReviewDecisionResponse(
        submission_id=result.submission_id,
        verdict=result.verdict,
        current_lesson_position=result.current_lesson_position,
        course_completed=result.course_completed,
    )
