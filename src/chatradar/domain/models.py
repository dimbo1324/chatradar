"""Единая модель сообщения. Каждый коннектор приводит свои данные к этому формату."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Source(StrEnum):
    TELEGRAM = "telegram"
    TG_EXPORT = "tg_export"
    WHATSAPP_EXPORT = "whatsapp_export"


class MediaType(StrEnum):
    NONE = "none"
    PHOTO = "photo"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    OTHER = "other"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChatInfo(_Frozen):
    source: Source
    chat_id: str
    title: str
    username: str | None = None


class RawRecord(_Frozen):
    """Неизменяемая сырая запись источника, как она лежит в `data/raw/*.jsonl`."""

    source: Source
    chat_id: str
    fetched_at: AwareDatetime
    payload: dict[str, Any]


class Message(_Frozen):
    source: Source
    chat_id: str  # строки: у разных мессенджеров разные ID
    msg_id: str
    author_id: str | None
    date: AwareDatetime  # всегда UTC
    text: str
    reply_to: str | None = None
    topic_id: str | None = None  # тема в форумах Telegram
    media_type: MediaType = MediaType.NONE
    is_forward: bool = False
    is_service: bool = False  # «вступил в группу» и т. п.
    edited_at: AwareDatetime | None = None
    link: str | None = None
    content_hash: str = Field(min_length=1)  # хэш значимых полей, ловит правки

    @property
    def key(self) -> tuple[Source, str, str]:
        return (self.source, self.chat_id, self.msg_id)
