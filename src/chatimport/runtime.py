"""Shared runtime contracts: what components see of a chat worker, notifications, the system
clock and disk. Wave-2 components (worker, trim, guards, control) meet only through these.

State rule: `state.json` on disk is the truth for everyone. Any component that changes a
chat's state or files does so while holding `ChatController.lock`, and starts by calling
`load_state(folder)` again, because another component may have changed it since.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator
    from pathlib import Path

    from chatimport.ports import ChatEvent


class Level(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @property
    def logging_level(self) -> int:
        return _LOGGING_LEVELS[self]


_LOGGING_LEVELS = {
    Level.INFO: logging.INFO,
    Level.WARNING: logging.WARNING,
    Level.ERROR: logging.ERROR,
}


class Notifier(Protocol):
    """User-visible notifications (tray toast, log). Never carries message text or names."""

    def notify(self, level: Level, title: str, message: str) -> None: ...


class LogNotifier:
    def __init__(self) -> None:
        self._log = logging.getLogger("chatimport.notify")

    def notify(self, level: Level, title: str, message: str) -> None:
        self._log.log(level.logging_level, "%s: %s", title, message)


@dataclass(frozen=True, slots=True)
class TrackedChat:
    """A library entry resolved to a real chat."""

    chat_id: int
    title: str
    username: str | None
    folder_name: str  # the folder to create when none exists yet, `<slug>_<chat_id>`


class BackfillState(StrEnum):
    """What the history download of one chat is doing now; the values go into `_status.json`."""

    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    DISK_STOPPED = "disk_stopped"
    RETRYING = "retrying"
    DONE = "done"
    NO_ACCESS = "no_access"
    IDLE = "idle"


@dataclass(frozen=True, slots=True)
class BackfillInfo:
    state: BackfillState = BackfillState.IDLE
    progress: float | None = None  # message ids are not dense, so this is only approximate
    month: str | None = None  # `YYYY-MM` being fetched now
    retry_at: datetime | None = None
    detail: str | None = None  # an exception type name, never a message


@dataclass(frozen=True, slots=True)
class ChatStatus:
    chat_id: int
    title: str
    phase: str  # a storage.state PHASE_* value
    last_id: int
    backfill_done: bool
    oldest_date: datetime | None
    records: int
    paused: bool
    error: str | None = None
    newest_date: datetime | None = None
    last_contact_at: datetime | None = None
    backfill: BackfillInfo = field(default_factory=BackfillInfo)


class ChatHandle(Protocol):
    """What file-level maintenance (trim, media, integrity) needs of a chat: its id, its folder
    and the lock that every writer of that folder holds."""

    @property
    def chat_id(self) -> int: ...

    @property
    def folder(self) -> Path: ...

    @property
    def lock(self) -> asyncio.Lock: ...


class ChatController(ChatHandle, Protocol):
    """The handle on one chat worker that the router, trimmer, guards and control use."""

    def submit(self, event: ChatEvent) -> None:
        """Queue a live event for this chat; never blocks."""
        ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def pause_backfill(self) -> None:
        """Stop only the background history download (disk guard); live goes on."""
        ...

    def resume_backfill(self) -> None: ...

    def request_refetch(self) -> None:
        """The chat folder was deleted: start again from HeadBackfill, floor reset."""
        ...

    def request_recheck(self, days: int | None = None) -> None:
        """Compare the last `days` days with Telegram at the next safe moment."""
        ...

    def status(self) -> ChatStatus: ...

    async def stop(self) -> None:
        """Flush the buffer and end the worker."""
        ...


@dataclass(slots=True)
class ChatRegistry:
    """The controllers of all active chats, by chat id."""

    _items: dict[int, ChatController] = field(default_factory=dict[int, ChatController])

    def add(self, controller: ChatController) -> None:
        self._items[controller.chat_id] = controller

    def remove(self, chat_id: int) -> ChatController | None:
        return self._items.pop(chat_id, None)

    def get(self, chat_id: int) -> ChatController | None:
        return self._items.get(chat_id)

    def all(self) -> list[ChatController]:
        return list(self._items.values())

    def __iter__(self) -> Iterator[ChatController]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._items)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class SystemDiskUsage:
    def free_bytes(self, path: Path) -> int:
        target = path
        while not target.exists() and target != target.parent:
            target = target.parent
        return shutil.disk_usage(target).free


class BackfillSlots:
    """At most `limit` chats download history at once; waiting chats get a slot in arrival
    order. A chat that already holds a slot may enter again without waiting."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        self._limit = limit
        self._depth: dict[int, int] = {}
        self._waiters: deque[tuple[int, asyncio.Future[None]]] = deque()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def holders(self) -> tuple[int, ...]:
        return tuple(self._depth)

    @property
    def waiting(self) -> tuple[int, ...]:
        return tuple(chat_id for chat_id, future in self._waiters if not future.done())

    @contextlib.asynccontextmanager
    async def acquire(self, chat_id: int) -> AsyncGenerator[None]:
        await self._enter(chat_id)
        try:
            yield
        finally:
            self._leave(chat_id)

    async def _enter(self, chat_id: int) -> None:
        if chat_id in self._depth:
            self._depth[chat_id] += 1
            return
        if len(self._depth) < self._limit and not self.waiting:
            self._depth[chat_id] = 1
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append((chat_id, future))
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                self._leave(chat_id)
            raise

    def _leave(self, chat_id: int) -> None:
        depth = self._depth[chat_id] - 1
        if depth:
            self._depth[chat_id] = depth
            return
        del self._depth[chat_id]
        while self._waiters and len(self._depth) < self._limit:
            waiter, future = self._waiters.popleft()
            if future.done():
                continue
            self._depth[waiter] = self._depth.get(waiter, 0) + 1
            future.set_result(None)
