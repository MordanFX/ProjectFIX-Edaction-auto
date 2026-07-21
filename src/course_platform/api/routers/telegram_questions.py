"""Curator-facing Telegram student question queue."""

from asyncio import to_thread
from collections.abc import AsyncIterator
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse

from course_platform.api.dependencies import (
    CurrentStaffDependency,
    SettingsDependency,
    TelegramQuestionServiceDependency,
)
from course_platform.api.schemas import (
    AttachmentPlaybackResponse,
    TelegramQuestionAnswerRequest,
    TelegramQuestionResponse,
)
from course_platform.api.security import (
    InvalidAccessTokenError,
    JWTConfigurationError,
    create_attachment_media_token,
    decode_attachment_media_token,
)
from course_platform.bot.api import TelegramAPIError, TelegramBotClient, TelegramTransportError
from course_platform.models.enums import AttachmentKind, StaffRole
from course_platform.models.staff import StaffUser
from course_platform.services.access_scope import StaffScope
from course_platform.services.telegram_questions import (
    EmptyQuestionAnswerError,
    QuestionAnswerAttachmentInput,
    TelegramQuestionAlreadyResolvedError,
    TelegramQuestionAttachmentNotFoundError,
    TelegramQuestionNotFoundError,
)

router = APIRouter(prefix="/telegram-questions", tags=["telegram-questions"])
PLAYBACK_TOKEN_TTL_SECONDS = 1800
MAX_ANSWER_UPLOAD_BYTES = 25 * 1024 * 1024


def _scope(staff: StaffUser) -> StaffScope:
    return StaffScope(staff_id=staff.id, is_admin=staff.role is StaffRole.ADMIN)


@router.get("", response_model=list[TelegramQuestionResponse])
async def telegram_questions(
    staff: CurrentStaffDependency,
    questions: TelegramQuestionServiceDependency,
    include_resolved: bool = True,
) -> list[TelegramQuestionResponse]:
    return [
        TelegramQuestionResponse.from_domain(item)
        for item in await questions.list_questions(
            include_resolved=include_resolved, viewer=_scope(staff)
        )
    ]


@router.post("/{question_id}/resolve", response_model=TelegramQuestionResponse)
async def resolve_telegram_question(
    question_id: UUID,
    staff: CurrentStaffDependency,
    questions: TelegramQuestionServiceDependency,
) -> TelegramQuestionResponse:
    try:
        item = await questions.resolve_question(
            question_id=question_id, staff_id=staff.id, viewer=_scope(staff)
        )
    except TelegramQuestionNotFoundError:
        raise HTTPException(status_code=404, detail="telegram-question-not-found") from None
    return TelegramQuestionResponse.from_domain(item)


async def _notify_student_of_answer(
    request: Request,
    settings: SettingsDependency,
    student_telegram_user_id: int | None,
    message: str,
    attachments: tuple[QuestionAnswerAttachmentInput, ...] = (),
) -> None:
    if student_telegram_user_id is None or settings.telegram_bot_token is None:
        return
    telegram = TelegramBotClient(
        settings.telegram_bot_token,
        api_url=settings.telegram_api_url,
        transport=request.app.state.telegram_transport,
    )
    try:
        await telegram.send_message(
            student_telegram_user_id,
            f"💬 <b>ОТВЕТ КУРАТОРА</b>\n\n{escape(message.strip())}",
            parse_mode="HTML",
        )
        for attachment in attachments:
            local_path = Path(attachment.local_path)
            if attachment.kind is AttachmentKind.PHOTO:
                await telegram.send_photo_file(
                    student_telegram_user_id,
                    local_path,
                    mime_type=attachment.mime_type or "image/jpeg",
                )
            else:
                await telegram.send_document_file(
                    student_telegram_user_id,
                    local_path,
                    mime_type=attachment.mime_type or "application/octet-stream",
                )
    except (TelegramAPIError, TelegramTransportError, OSError):
        pass
    finally:
        await telegram.close()


@router.post("/{question_id}/answer", response_model=TelegramQuestionResponse)
async def answer_telegram_question(
    question_id: UUID,
    payload: TelegramQuestionAnswerRequest,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    questions: TelegramQuestionServiceDependency,
    request: Request,
) -> TelegramQuestionResponse:
    try:
        result = await questions.answer_question(
            question_id=question_id,
            staff_id=staff.id,
            message=payload.message,
            viewer=_scope(staff),
        )
    except EmptyQuestionAnswerError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Answer message must not be empty",
        ) from None
    except TelegramQuestionNotFoundError:
        raise HTTPException(status_code=404, detail="telegram-question-not-found") from None
    except TelegramQuestionAlreadyResolvedError:
        raise HTTPException(status_code=409, detail="telegram-question-already-resolved") from None

    await _notify_student_of_answer(
        request, settings, result.student_telegram_user_id, payload.message
    )
    return TelegramQuestionResponse.from_domain(result.overview)


def _attachment_kind_from_upload(upload: UploadFile) -> AttachmentKind:
    content_type = upload.content_type or ""
    if content_type.startswith("image/"):
        return AttachmentKind.PHOTO
    if content_type.startswith("video/"):
        return AttachmentKind.VIDEO
    return AttachmentKind.DOCUMENT


async def _store_answer_upload(
    upload: UploadFile,
    settings: SettingsDependency,
) -> QuestionAnswerAttachmentInput:
    content = await upload.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Attachment file must not be empty",
        )
    if len(content) > MAX_ANSWER_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Attachment file is too large",
        )

    original_name = Path(upload.filename or "attachment").name
    suffix = Path(original_name).suffix[:32]
    upload_dir = Path(settings.feedback_upload_dir)
    await to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
    stored_path = upload_dir / f"{uuid4().hex}{suffix}"
    await to_thread(stored_path.write_bytes, content)
    return QuestionAnswerAttachmentInput(
        kind=_attachment_kind_from_upload(upload),
        local_path=str(stored_path),
        file_name=original_name,
        mime_type=upload.content_type,
        file_size=len(content),
    )


@router.post("/{question_id}/answer-with-attachment", response_model=TelegramQuestionResponse)
async def answer_telegram_question_with_attachment(
    question_id: UUID,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    questions: TelegramQuestionServiceDependency,
    request: Request,
    message: Annotated[str, Form()] = "",
    attachments: Annotated[list[UploadFile] | None, File()] = None,
) -> TelegramQuestionResponse:
    uploads = attachments or []
    stored_attachments = tuple(
        [await _store_answer_upload(upload, settings) for upload in uploads]
    )
    try:
        result = await questions.answer_question(
            question_id=question_id,
            staff_id=staff.id,
            message=message,
            attachments=stored_attachments,
            viewer=_scope(staff),
        )
    except EmptyQuestionAnswerError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Answer message or attachment must not be empty",
        ) from None
    except TelegramQuestionNotFoundError:
        raise HTTPException(status_code=404, detail="telegram-question-not-found") from None
    except TelegramQuestionAlreadyResolvedError:
        raise HTTPException(status_code=409, detail="telegram-question-already-resolved") from None

    await _notify_student_of_answer(
        request,
        settings,
        result.student_telegram_user_id,
        result.overview.answer_text or "",
        attachments=stored_attachments,
    )
    return TelegramQuestionResponse.from_domain(result.overview)


@router.post(
    "/{question_id}/attachments/{attachment_id}/playback",
    response_model=AttachmentPlaybackResponse,
)
async def create_telegram_question_attachment_playback(
    question_id: UUID,
    attachment_id: UUID,
    request: Request,
    staff: CurrentStaffDependency,
    settings: SettingsDependency,
    questions: TelegramQuestionServiceDependency,
) -> AttachmentPlaybackResponse:
    try:
        await questions.get_attachment_media_source(
            question_id=question_id, attachment_id=attachment_id
        )
        token = create_attachment_media_token(
            staff_id=staff.id,
            submission_id=question_id,
            attachment_id=attachment_id,
            settings=settings,
            expires_in_seconds=PLAYBACK_TOKEN_TTL_SECONDS,
        )
    except TelegramQuestionAttachmentNotFoundError:
        raise HTTPException(status_code=404, detail="Attachment not found") from None
    except JWTConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Media playback is not configured",
        ) from None

    media_url = request.url_for(
        "stream_telegram_question_attachment",
        question_id=str(question_id),
        attachment_id=str(attachment_id),
    )
    return AttachmentPlaybackResponse(
        url=f"{media_url.path}?token={quote(token)}",
        expires_in=PLAYBACK_TOKEN_TTL_SECONDS,
    )


@router.get(
    "/{question_id}/attachments/{attachment_id}/media",
    name="stream_telegram_question_attachment",
    response_model=None,
)
async def stream_telegram_question_attachment(
    question_id: UUID,
    attachment_id: UUID,
    token: str,
    request: Request,
    settings: SettingsDependency,
    questions: TelegramQuestionServiceDependency,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> FileResponse | StreamingResponse:
    try:
        claims = decode_attachment_media_token(token, settings)
    except (InvalidAccessTokenError, JWTConfigurationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired media token",
        ) from None
    if claims.submission_id != question_id or claims.attachment_id != attachment_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Media token mismatch")

    try:
        source = await questions.get_attachment_media_source(
            question_id=question_id, attachment_id=attachment_id
        )
    except TelegramQuestionAttachmentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        ) from None

    if source.local_path is not None:
        local_path = Path(source.local_path)
        if await to_thread(local_path.is_file):
            return FileResponse(
                local_path,
                media_type=source.mime_type or "application/octet-stream",
                filename=source.file_name,
                content_disposition_type="inline",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment file is unavailable",
        )

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
