"""Builders for chat folders and a controller double shared by the maintenance tests."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from chatimport.records import MessageRecord
from chatimport.runtime import ChatStatus
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import PHASE_LIVE, ChatState, load_state, new_state
from chatimport.storage.writer import ChunkWriter, iter_records
from tests.fakes import NOW, msg

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from pathlib import Path

    from chatimport.ports import ChatEvent
    from chatimport.records import Record
    from tests.fakes import FakeClock

ONE_BYTE_PARTS = 1


def at(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def mmsg(
    msg_id: int, month: int = 9, day: int = 10, *, chat_id: int, text: str | None = None
) -> MessageRecord:
    """A message dated 2026-<month>-<day> with the hour derived from the id."""
    return msg(msg_id, chat_id=chat_id, date=at(2026, month, day, msg_id % 24), text=text)


class FakeController:
    """A `runtime.ChatController` with a real lock and a record of every call."""

    def __init__(
        self,
        chat_id: int,
        folder: Path,
        title: str = "Chat",
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._chat_id = chat_id
        self._folder = folder
        self._lock = lock or asyncio.Lock()
        self.title = title
        self.calls: list[str] = []
        self.events: list[ChatEvent] = []

    @property
    def chat_id(self) -> int:
        return self._chat_id

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def submit(self, event: ChatEvent) -> None:
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
        self.calls.append("request_refetch")

    def request_recheck(self, days: int | None = None) -> None:
        self.calls.append(f"request_recheck:{days}")

    def status(self) -> ChatStatus:
        return ChatStatus(
            chat_id=self._chat_id,
            title=self.title,
            phase=PHASE_LIVE,
            last_id=0,
            backfill_done=True,
            oldest_date=None,
            records=0,
            paused=False,
        )

    async def stop(self) -> None:
        self.calls.append("stop")


def build_chat(
    root: Path,
    chat_id: int,
    batches: Sequence[Sequence[Record]],
    *,
    title: str = "Chat",
    max_chunk_bytes: int = ONE_BYTE_PARTS,
    now: datetime = NOW,
) -> FakeController:
    """Write each batch with the real `ChunkWriter`.

    With one-byte parts every batch becomes its own part, so the batches define the parts.
    """
    folder = root / chat_folder_name(title, chat_id)
    folder.mkdir(parents=True, exist_ok=True)
    state: ChatState = new_state(chat_id, title, None, now)
    writer = ChunkWriter(folder, max_chunk_bytes, lambda: now)
    state = writer.update_state(state)
    for batch in batches:
        state = writer.append(state, list(batch))
    return FakeController(chat_id, folder, title)


def read_state(controller: FakeController) -> ChatState:
    state = load_state(controller.folder)
    assert state is not None
    return state


def message_ids(controller: FakeController) -> list[int]:
    return [r.msg_id for r in iter_records(controller.folder) if isinstance(r, MessageRecord)]


def assert_state_matches_files(controller: FakeController) -> None:
    """The chunk accounting in state.json equals what the part files really hold."""
    from chatimport.storage.layout import list_parts
    from chatimport.storage.writer import scan_part

    state = read_state(controller)
    parts = list_parts(controller.folder)
    assert sorted(state.chunks) == [p.stem for p in parts]
    for path in parts:
        assert state.chunks[path.stem] == scan_part(path)
        assert state.chunks[path.stem].bytes == path.stat().st_size


async def drive(run: Callable[[], Awaitable[None]], clock: FakeClock, cycles: int) -> None:
    """Run an endless `run()` loop for `cycles` sleeps, then cancel it from inside the clock."""

    def stop(_: float) -> None:
        if len(clock.sleeps) >= cycles:
            raise asyncio.CancelledError

    clock.on_sleep = stop
    with contextlib.suppress(asyncio.CancelledError):
        await run()
