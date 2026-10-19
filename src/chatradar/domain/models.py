"""The unified message model and the read models built on it.

Every connector maps its data to `Message`; everything after ingestion works only with
these types. They are the contract between packages — change them only through the lead.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class Source(StrEnum):
    """The messenger a chat lives in. A chat keeps its source whichever way it was fetched."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class RawKind(StrEnum):
    """The payload format of a raw record: who produced it."""

    TELETHON = "telethon"  # Message.to_dict() from Telethon
    TG_DESKTOP = "tg_desktop"  # one message object of a Telegram Desktop JSON export


class ChatKind(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class MediaType(StrEnum):
    NONE = "none"
    PHOTO = "photo"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"
    OTHER = "other"


type MessageKey = tuple[Source, str, str]
"""(source, chat_id, msg_id) — the identity of a message everywhere."""

type ResultValue = str | int | float | bool | list[str] | None


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChatInfo(_Frozen):
    """A chat. `chat_id` uses Telegram's marked form: `-100<id>` for supergroups and channels."""

    source: Source
    chat_id: str
    title: str
    username: str | None = None
    kind: ChatKind = ChatKind.SUPERGROUP


class RawRecord(_Frozen):
    """One source message exactly as received; one line of `data/raw/**/*.jsonl`."""

    source: Source
    kind: RawKind
    chat_id: str
    fetched_at: AwareDatetime
    payload: dict[str, Any]


class SyncState(_Frozen):
    source: Source
    chat_id: str
    last_id: str | None = None
    last_sync_at: AwareDatetime | None = None


class Message(_Frozen):
    """A normalized message. Produced by a mapper from one `RawRecord`."""

    source: Source
    chat_id: str  # strings: messengers use different id types
    msg_id: str
    author_id: str | None
    date: AwareDatetime  # always UTC
    text: str  # normalized: NFC, trimmed, collapsed blank lines
    text_raw: str = ""  # as received
    reply_to: str | None = None
    topic_id: str | None = None  # topic in Telegram forum groups
    media_type: MediaType = MediaType.NONE
    is_forward: bool = False
    is_service: bool = False  # "joined the group" and similar
    edited_at: AwareDatetime | None = None
    link: str | None = None
    content_hash: str = Field(min_length=1)  # domain.text.content_hash, detects edits

    @property
    def key(self) -> MessageKey:
        return (self.source, self.chat_id, self.msg_id)


class StoredMessage(Message):
    """A message as stored, with the columns the pipeline stages fill in."""

    lang: str | None = None
    is_question: bool | None = None
    urls: tuple[str, ...] = ()
    has_mention: bool | None = None
    is_noise: bool | None = None
    noise_reason: str | None = None
    thread_id: str | None = None
    versions: dict[str, int] = Field(default_factory=dict)  # stage name -> version done


class StageResult(_Frozen):
    """Column values one stage computed for one message (see pipeline.base.STAGE_COLUMNS)."""

    key: MessageKey
    values: dict[str, ResultValue] = Field(default_factory=dict)


class UpsertResult(_Frozen):
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    def __add__(self, other: UpsertResult) -> UpsertResult:
        return UpsertResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
        )


class Thread(_Frozen):
    """A discussion: messages joined by replies and time proximity."""

    thread_id: str  # f"{chat_id}:{root_msg_id}", stable
    source: Source
    chat_id: str
    topic_id: str | None = None
    root_msg_id: str
    started_at: AwareDatetime
    ended_at: AwareDatetime
    msg_count: int = Field(ge=1)
    has_question: bool = False


# ---------------------------------------------------------------- read models (web, API)


class ChatSummary(_Frozen):
    chat: ChatInfo
    message_count: int = 0
    noise_count: int = 0
    thread_count: int = 0
    first_message_at: AwareDatetime | None = None
    last_message_at: AwareDatetime | None = None
    last_sync_at: AwareDatetime | None = None


class StageStat(_Frozen):
    stage: str
    version: int
    done: int  # messages with this stage at the current version
    pending: int  # messages still to process at this version


class PipelineStats(_Frozen):
    total_messages: int
    stages: list[StageStat]


class MessageFilter(_Frozen):
    source: Source | None = None
    chat_id: str | None = None
    date_from: AwareDatetime | None = None
    date_to: AwareDatetime | None = None
    lang: str | None = None
    is_noise: bool | None = None
    noise_reason: str | None = None
    is_question: bool | None = None
    thread_id: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class MessagePage(_Frozen):
    items: list[StoredMessage]
    total: int
    limit: int
    offset: int


class SearchFilters(_Frozen):
    source: Source | None = None
    chat_id: str | None = None
    date_from: AwareDatetime | None = None
    date_to: AwareDatetime | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ThreadHit(_Frozen):
    thread: Thread
    score: float  # higher is better
    snippet: str  # short plain-text excerpt; matched words wrapped in [[ and ]]
    link: str | None = None  # link to the thread's root message


class ThreadDetail(_Frozen):
    thread: Thread
    messages: list[StoredMessage]  # chronological; noise messages belong to no thread
