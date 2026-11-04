"""Shared test doubles: a deterministic clock, a scripted Telegram gateway and a recording
notifier. Telegram is never called from tests; everything goes through these."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from chatimport.ports import (
    ChatEvent,
    DialogInfo,
    EventHandler,
    ResolvedChat,
    ResolveStatus,
)
from chatimport.records import MessageRecord

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from chatimport.records import MediaInfo
    from chatimport.runtime import Level

NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
CHAT_ID = -1001234567890


def msg(
    msg_id: int,
    *,
    chat_id: int = CHAT_ID,
    date: datetime | None = None,
    text: str | None = None,
    edit_date: datetime | None = None,
    media: MediaInfo | None = None,
    fetched_at: datetime = NOW,
    **extra: Any,
) -> MessageRecord:
    """A message dated `1000 - msg_id` hours before NOW unless a date is given."""
    return MessageRecord(
        chat_id=chat_id,
        msg_id=msg_id,
        date=date if date is not None else NOW - timedelta(hours=1000 - msg_id),
        fetched_at=fetched_at,
        text=f"text {msg_id}" if text is None else text,
        edit_date=edit_date,
        media=media,
        **extra,
    )


class FakeClock:
    """`sleep` never waits: it advances `now` and records the request."""

    def __init__(self, start: datetime = NOW) -> None:
        self._now = start
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[float], None] | None = None

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += timedelta(seconds=seconds)
        if self.on_sleep is not None:
            self.on_sleep(seconds)
        await asyncio.sleep(0)


class FakeDisk:
    """`free_bytes` returns scripted values; the last one repeats."""

    def __init__(self, *free: int) -> None:
        self.values = list(free) or [10**15]
        self.calls = 0

    def free_bytes(self, path: Path) -> int:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


@dataclass
class Note:
    level: Level
    title: str
    message: str


class RecordingNotifier:
    def __init__(self) -> None:
        self.notes: list[Note] = []

    def notify(self, level: Level, title: str, message: str) -> None:
        self.notes.append(Note(level, title, message))

    def titles(self) -> list[str]:
        return [n.title for n in self.notes]


@dataclass
class FakeGateway:
    """A scripted `TelegramGateway`.

    - `chats[chat_id]` holds `{msg_id: MessageRecord}`; iteration follows ports.py semantics.
    - `fail[method]` is a list of exceptions raised (and consumed) by the next calls of that method.
    - `calls` logs `(method, args)` for assertions; `fire(event)` feeds registered handlers.
    """

    chats: dict[int, dict[int, MessageRecord]] = field(
        default_factory=dict[int, dict[int, MessageRecord]]
    )
    dialogs: list[DialogInfo] = field(default_factory=list[DialogInfo])
    refs: dict[str, ResolvedChat] = field(default_factory=dict[str, ResolvedChat])
    media: dict[tuple[int, int], bytes] = field(default_factory=dict[tuple[int, int], bytes])
    fail: dict[str, list[BaseException]] = field(default_factory=dict[str, list[BaseException]])
    calls: list[tuple[str, tuple[Any, ...]]] = field(
        default_factory=list[tuple[str, tuple[Any, ...]]]
    )
    handlers: list[EventHandler] = field(default_factory=list[EventHandler])
    connected: bool = False
    page_hook: Callable[[], None] | None = None

    def add_chat(self, chat_id: int, ids: range | list[int], **kw: Any) -> None:
        self.chats[chat_id] = {i: msg(i, chat_id=chat_id, **kw) for i in ids}

    def _maybe_fail(self, method: str) -> None:
        queue = self.fail.get(method)
        if queue:
            raise queue.pop(0)

    async def connect(self) -> None:
        self.calls.append(("connect", ()))
        self._maybe_fail("connect")
        self.connected = True

    async def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))
        self.connected = False

    async def list_dialogs(self) -> list[DialogInfo]:
        self.calls.append(("list_dialogs", ()))
        self._maybe_fail("list_dialogs")
        return list(self.dialogs)

    async def resolve(self, ref: str) -> ResolvedChat:
        self.calls.append(("resolve", (ref,)))
        self._maybe_fail("resolve")
        return self.refs.get(ref, ResolvedChat(ref, ResolveStatus.NOT_FOUND))

    async def newest_id(self, chat_id: int) -> int:
        self.calls.append(("newest_id", (chat_id,)))
        self._maybe_fail("newest_id")
        return max(self.chats.get(chat_id, {}), default=0)

    async def iter_history(
        self, chat_id: int, *, offset_id: int = 0, min_id: int = 0
    ) -> AsyncIterator[MessageRecord]:
        self.calls.append(("iter_history", (chat_id, offset_id, min_id)))
        self._maybe_fail("iter_history")
        for i in sorted(self.chats.get(chat_id, {}), reverse=True):
            if (offset_id and i >= offset_id) or i <= min_id:
                continue
            if self.page_hook:
                self.page_hook()
            self._maybe_fail("iter_history_item")
            yield self.chats[chat_id][i]

    async def iter_since(self, chat_id: int, min_id: int) -> AsyncIterator[MessageRecord]:
        self.calls.append(("iter_since", (chat_id, min_id)))
        self._maybe_fail("iter_since")
        for i in sorted(self.chats.get(chat_id, {})):
            if i > min_id:
                if self.page_hook:
                    self.page_hook()
                yield self.chats[chat_id][i]

    async def iter_window(
        self, chat_id: int, since: datetime, max_id: int
    ) -> AsyncIterator[MessageRecord]:
        self.calls.append(("iter_window", (chat_id, since, max_id)))
        self._maybe_fail("iter_window")
        for i in sorted(self.chats.get(chat_id, {})):
            record = self.chats[chat_id][i]
            if i <= max_id and record.date >= since:
                yield record

    def add_event_handler(self, handler: EventHandler) -> None:
        self.handlers.append(handler)

    async def fire(self, event: ChatEvent) -> None:
        for handler in list(self.handlers):
            await handler(event)

    async def download_media(self, chat_id: int, msg_id: int, target_dir: Path) -> Path | None:
        self.calls.append(("download_media", (chat_id, msg_id)))
        self._maybe_fail("download_media")
        data = self.media.get((chat_id, msg_id))
        if data is None:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        path = target_dir / f"tg_{chat_id}_{msg_id}.bin"
        path.write_bytes(data)
        return path

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)
