from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from chatimport.runtime import ChatStatus
from chatimport.storage.state import PHASE_LIVE

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import ChatEvent


class StubController:
    """A `ChatController` that records what it was asked to do."""

    def __init__(self, chat_id: int, folder: Path | None = None, *, title: str = "Chat") -> None:
        self._chat_id = chat_id
        self._folder = folder
        self.title = title
        self.lock_obj = asyncio.Lock()
        self.events: list[ChatEvent] = []
        self.calls: list[str] = []
        self.fail_submit: BaseException | None = None
        self.last_id = 0
        self.records = 0
        self.error: str | None = None

    @property
    def chat_id(self) -> int:
        return self._chat_id

    @property
    def folder(self) -> Path:
        assert self._folder is not None
        return self._folder

    @property
    def lock(self) -> asyncio.Lock:
        return self.lock_obj

    def submit(self, event: ChatEvent) -> None:
        if self.fail_submit is not None:
            raise self.fail_submit
        self.events.append(event)

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def pause_backfill(self) -> None:
        self.calls.append("pause_backfill")

    def resume_backfill(self) -> None:
        self.calls.append("resume_backfill")

    def request_refetch(self) -> None:
        self.calls.append("refetch")

    def request_recheck(self, days: int | None = None) -> None:
        self.calls.append(f"recheck:{days}")

    def status(self) -> ChatStatus:
        return ChatStatus(
            chat_id=self._chat_id,
            title=self.title,
            phase=PHASE_LIVE,
            last_id=self.last_id,
            backfill_done=True,
            oldest_date=None,
            records=self.records,
            paused=False,
            error=self.error,
        )

    async def stop(self) -> None:
        self.calls.append("stop")
