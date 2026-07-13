"""Minimal Telegram Bot API types used by the learning bot."""

from pydantic import BaseModel, ConfigDict, Field


class TelegramModel(BaseModel):
    """Ignore new Bot API fields until the application needs them."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class TelegramFile(TelegramModel):
    file_id: str
    file_unique_id: str
    file_size: int | None = None
    file_path: str | None = None


class TelegramUser(TelegramModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TelegramChat(TelegramModel):
    id: int
    type: str
    title: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class TelegramDocument(TelegramModel):
    file_id: str
    file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TelegramPhotoSize(TelegramModel):
    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: int | None = None


class TelegramVideo(TelegramModel):
    file_id: str
    file_unique_id: str
    width: int
    height: int
    duration: int
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TelegramVideoNote(TelegramModel):
    file_id: str
    file_unique_id: str
    length: int
    duration: int
    file_size: int | None = None


class TelegramMessage(TelegramModel):
    message_id: int
    date: int
    chat: TelegramChat
    sender: TelegramUser | None = Field(default=None, alias="from")
    text: str | None = None
    caption: str | None = None
    document: TelegramDocument | None = None
    photo: list[TelegramPhotoSize] = Field(default_factory=list)
    video: TelegramVideo | None = None
    video_note: TelegramVideoNote | None = None


class TelegramCallbackQuery(TelegramModel):
    id: str
    sender: TelegramUser = Field(alias="from")
    message: TelegramMessage | None = None
    data: str | None = None


class TelegramUpdate(TelegramModel):
    update_id: int
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None
