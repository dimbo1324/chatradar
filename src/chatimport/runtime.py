"""Shared runtime contracts: what components see of a chat worker, notifications, the system
clock and disk. Wave-2 components (worker, trim, guards, control) meet only through these.

State rule: `state.json` on disk is the truth for everyone. Any component that changes a
chat's state or files does so while holding `ChatController.lock`, and starts by calling
`load_state(folder)` again, because another component may have changed it since.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from chatimport.ports import ChatEvent


class Level(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Notifier(Protocol):
    """User-visible notifications (tray toast, log). Never carries message text or names."""

    def notify(self, level: Level, title: str, message: str) -> None: ...


class LogNotifier:
    def __init__(self) -> None:
        import logging

        self._log = logging.getLogger("chatimport.notify")

    def notify(self, level: Level, title: str, message: str) -> None:
        self._log.log(
            {"info": 20, "warning": 30, "error": 40}[level.value], "%s: %s", title, message
        )


@dataclass(frozen=True, slots=True)
class TrackedChat:
    """A library entry resolved to a real chat."""

    chat_id: int
    title: str
    username: str | None
    folder_name: str  # the folder to create when none exists yet, `<slug>_<chat_id>`


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


class ChatController(Protocol):
    """The handle on one chat worker that the router, trimmer, guards and control use."""

    @property
    def chat_id(self) -> int: ...

    @property
    def folder(self) -> Path: ...

    @property
    def lock(self) -> asyncio.Lock: ...

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
