"""Seams between the service and the outside world. Telethon, the disk and the clock enter
through these, so every other module is testable without network or a real disk."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.records import MessageRecord


class ChatImportError(Exception):
    """Base class of expected, handled failures."""


class FloodWait(ChatImportError):
    """Telegram asks to wait longer than the configured sleep threshold."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"Telegram FloodWait: {seconds} s")
        self.seconds = seconds


class AccessLost(ChatImportError):
    """The account was removed from, or banned in, a chat."""

    def __init__(self, chat_id: int) -> None:
        super().__init__(f"no access to chat {chat_id}")
        self.chat_id = chat_id


class SessionRevoked(ChatImportError):
    """The Telegram session is gone; `chatimport login` is needed."""


class ResolveStatus(StrEnum):
    FOUND = "found"
    NEED_TO_JOIN = "need_to_join"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    NOT_A_CHAT = "not_a_chat"  # a person or a bot


@dataclass(frozen=True, slots=True)
class ResolvedChat:
    ref: str
    status: ResolveStatus
    chat_id: int | None = None
    title: str | None = None
    username: str | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DialogInfo:
    """A group or channel of the account, as listed by `chatimport dialogs`."""

    chat_id: int
    title: str
    username: str | None
    link: str | None
    kind: str  # "group" | "supergroup" | "channel"


@dataclass(frozen=True, slots=True)
class NewMessageEvent:
    record: MessageRecord


@dataclass(frozen=True, slots=True)
class EditedMessageEvent:
    record: MessageRecord  # the message as it is now; `edit_date` is set


@dataclass(frozen=True, slots=True)
class DeletedMessagesEvent:
    chat_id: int | None  # None for basic small groups (spec §6.2)
    msg_ids: tuple[int, ...]


type ChatEvent = NewMessageEvent | EditedMessageEvent | DeletedMessagesEvent
type EventHandler = Callable[[ChatEvent], Awaitable[None]]


class TelegramGateway(Protocol):
    """Everything the service needs from Telegram. Implemented by `telegram.client`."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def list_dialogs(self) -> list[DialogInfo]: ...

    async def resolve(self, ref: str) -> ResolvedChat: ...

    async def newest_id(self, chat_id: int) -> int:
        """Id of the newest message in the chat, 0 when it is empty."""
        ...

    def iter_history(
        self, chat_id: int, *, offset_id: int = 0, min_id: int = 0
    ) -> AsyncIterator[MessageRecord]:
        """Newest to oldest. Only messages with `min_id < id < offset_id` (0 = unbounded)."""
        ...

    def iter_since(self, chat_id: int, min_id: int) -> AsyncIterator[MessageRecord]:
        """Oldest to newest: every message with `id > min_id`."""
        ...

    def iter_window(
        self, chat_id: int, since: datetime, max_id: int
    ) -> AsyncIterator[MessageRecord]:
        """Oldest to newest: messages dated `>= since` with `id <= max_id`."""
        ...

    def add_event_handler(self, handler: EventHandler) -> None:
        """Register one handler for new, edited and deleted message events."""
        ...

    async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
        """Refetch the message and download its media into `target_dir`; None if unavailable."""
        ...


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class DiskUsage(Protocol):
    def free_bytes(self, path: Path) -> int: ...
