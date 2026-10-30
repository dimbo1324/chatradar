"""Harness for worker tests: a real `ChatWorker` over a scripted gateway and a fake clock.

Nothing here sleeps for real. The worker is driven by yielding to the event loop until a
condition on the disk or the state file holds.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.config import Config, parse_config
from chatimport.ports import (
    DeletedMessagesEvent,
    EditedMessageEvent,
    NewMessageEvent,
)
from chatimport.recheck import compute_recheck
from chatimport.records import MessageRecord
from chatimport.runtime import TrackedChat
from chatimport.storage.layout import chat_folder_name, list_parts
from chatimport.storage.state import PHASE_LIVE, ChatState, load_state
from chatimport.storage.writer import iter_part_records, iter_records, scan_part
from chatimport.worker import ChatWorker, RecheckFn
from tests.fakes import CHAT_ID, NOW, FakeClock, FakeGateway, RecordingNotifier, msg

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable
    from pathlib import Path

TITLE = "Example Chat"
TURNS = 30000


def make_config(**sections: dict[str, Any]) -> Config:
    return parse_config(dict(sections))


@dataclass
class Rig:
    root: Path
    gateway: FakeGateway
    clock: FakeClock
    notifier: RecordingNotifier
    config: Config
    chat: TrackedChat
    worker: ChatWorker
    task: asyncio.Task[None] | None = None

    @property
    def folder(self) -> Path:
        return self.worker.folder

    def start(self) -> asyncio.Task[None]:
        self.task = asyncio.create_task(self.worker.run())
        return self.task

    async def until(self, predicate: Callable[[], bool], what: str = "condition") -> None:
        for _ in range(TURNS):
            if predicate():
                return
            task = self.task
            if task is not None and task.done():
                outcome = "cancelled" if task.cancelled() else repr(task.exception())
                raise AssertionError(f"worker ended ({outcome}) before: {what}")
            await asyncio.sleep(0)
        raise AssertionError(f"not reached: {what}")

    async def settle(self, turns: int = 400) -> None:
        for _ in range(turns):
            await asyncio.sleep(0)

    def load(self) -> ChatState | None:
        return load_state(self.folder)

    def state(self) -> ChatState:
        state = self.load()
        assert state is not None, "state.json is missing"
        return state

    def phase(self) -> str | None:
        state = self.load()
        return state.phase if state is not None else None

    def is_live(self) -> bool:
        return self.phase() == PHASE_LIVE

    def backfill_done(self) -> bool:
        state = self.load()
        return state is not None and state.backfill.done

    async def until_live(self) -> None:
        await self.until(self.is_live, "phase live")

    async def until_complete(self) -> None:
        await self.until(lambda: self.is_live() and self.backfill_done(), "live and backfilled")

    def ids(self) -> list[int]:
        return disk_ids(self.folder)

    async def shutdown(self) -> None:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(self.worker.stop(), 3)
        task = self.task
        if task is None:
            return
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def kill(self) -> None:
        """A hard stop: cancel the run task without any graceful flush request."""
        task = self.task
        assert task is not None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class RigFactory:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.rigs: list[Rig] = []

    def __call__(
        self,
        ids: Iterable[int] | None = None,
        *,
        chat_id: int = CHAT_ID,
        title: str = TITLE,
        config: Config | None = None,
        gateway: FakeGateway | None = None,
        clock: FakeClock | None = None,
        notifier: RecordingNotifier | None = None,
        recheck: RecheckFn | None = None,
    ) -> Rig:
        gateway = gateway if gateway is not None else FakeGateway()
        if ids is not None:
            gateway.add_chat(chat_id, list(ids))
        clock = clock if clock is not None else FakeClock()
        notifier = notifier if notifier is not None else RecordingNotifier()
        config = config if config is not None else make_config()
        chat = TrackedChat(chat_id, title, None, chat_folder_name(title, chat_id))
        worker = ChatWorker(
            chat,
            root=self.root,
            gateway=gateway,
            config=config,
            clock=clock,
            notifier=notifier,
            recheck=recheck if recheck is not None else compute_recheck,
        )
        rig = Rig(self.root, gateway, clock, notifier, config, chat, worker)
        self.rigs.append(rig)
        return rig


@pytest.fixture
async def make_rig(tmp_path: Path) -> AsyncIterator[RigFactory]:
    factory = RigFactory(tmp_path / "ChatImport")
    yield factory
    for rig in factory.rigs:
        await rig.shutdown()


@pytest.fixture
def small_parts(monkeypatch: pytest.MonkeyPatch) -> int:
    """Parts of 2 KiB instead of megabytes, so a few hundred messages span many parts."""
    monkeypatch.setattr("chatimport.worker._BYTES_PER_MB", 2048)
    return 2048


def disk_ids(folder: Path) -> list[int]:
    return [r.msg_id for r in iter_records(folder) if isinstance(r, MessageRecord)]


def assert_disk_consistent(
    folder: Path, *, expect_ids: Iterable[int] | None = None, ordered: bool = True
) -> list[int]:
    """The files and `state.json` agree, no message appears twice, nothing is half-written."""
    state = load_state(folder)
    assert state is not None, "state.json is missing or unreadable"
    parts = list_parts(folder)
    ids = disk_ids(folder)
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicated message ids: {duplicates[:10]}"
    assert {p.stem for p in parts} == set(state.chunks), "chunks do not match the part files"
    for part in parts:
        assert scan_part(part) == state.chunks[part.stem], f"chunk accounting off for {part.name}"
        assert part.read_bytes().endswith(b"\n"), f"{part.name} does not end with a newline"
    assert not list(folder.glob(".*.tmp")), "temp files left behind"
    if ordered:
        assert ids == sorted(ids), "messages are not in ascending id order"
        for part in parts:
            part_ids = [r.msg_id for r in iter_part_records(part) if isinstance(r, MessageRecord)]
            assert part_ids == sorted(part_ids)
    assert state.last_id >= max(ids, default=0)
    if expect_ids is not None:
        assert set(ids) == set(expect_ids)
    return ids


def new_event(msg_id: int, **kwargs: Any) -> NewMessageEvent:
    return NewMessageEvent(msg(msg_id, **kwargs))


def edit_event(
    msg_id: int, text: str, edit_date: datetime | None = None, **kwargs: Any
) -> EditedMessageEvent:
    when = edit_date if edit_date is not None else NOW + timedelta(minutes=1)
    return EditedMessageEvent(msg(msg_id, text=text, edit_date=when, **kwargs))


def delete_event(ids: Iterable[int], chat_id: int | None = CHAT_ID) -> DeletedMessagesEvent:
    return DeletedMessagesEvent(chat_id, tuple(ids))


def future_message(msg_id: int, hours: float = 0.0, **kwargs: Any) -> MessageRecord:
    """A message after the pre-built history (which ends at NOW)."""
    return msg(msg_id, date=NOW + timedelta(hours=hours + (msg_id - 1000) / 100), **kwargs)
