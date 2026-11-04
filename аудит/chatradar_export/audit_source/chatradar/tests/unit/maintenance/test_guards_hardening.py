from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from chatimport.config import GIB, DiskConfig, WatchConfig
from chatimport.guards.disk import DiskGuard, MediaDiskGate
from chatimport.guards.folders import FolderWatcher
from chatimport.runtime import ChatRegistry, Level
from chatimport.storage.layout import STATE_FILE, list_parts
from chatimport.storage.state import BackfillState, ChunkInfo, save_state
from tests.fakes import NOW, FakeClock, FakeDisk, RecordingNotifier
from tests.unit.maintenance.helpers import FakeController, build_chat, mmsg, read_state

if TYPE_CHECKING:
    from chatimport.trim import TrimmedPart

CHAT = -100


class NoTrim:
    async def delete_oldest_part(self, protect_recent_days: int) -> TrimmedPart | None:
        return None


def guard_for(root: Path, *chats: FakeController, free: int) -> tuple[DiskGuard, RecordingNotifier]:
    registry = ChatRegistry()
    for chat in chats:
        registry.add(chat)
    notifier = RecordingNotifier()
    guard = DiskGuard(
        root,
        registry,
        NoTrim(),  # pyright: ignore[reportArgumentType]
        DiskConfig(),
        clock=FakeClock(),
        disk=FakeDisk(free),
        notifier=notifier,
    )
    return guard, notifier


def chat_in_tail(root: Path, chat_id: int, oldest_done: int) -> FakeController:
    chat = build_chat(
        root, chat_id, [[mmsg(i, chat_id=chat_id)] for i in (5, 6)], title=str(chat_id)
    )
    state = read_state(chat)
    save_state(
        chat.folder, replace(state, backfill=BackfillState(head_id=6, oldest_done_id=oldest_done))
    )
    return chat


async def test_disk_guard_stops_backfill_persistently(tmp_path: Path) -> None:
    root = tmp_path / "root"
    tail = chat_in_tail(root, CHAT, oldest_done=5)
    fresh = chat_in_tail(root, -2, oldest_done=0)
    done = build_chat(root, -3, [[mmsg(1, chat_id=-3)]], title="done")
    save_state(done.folder, replace(read_state(done), backfill=BackfillState(done=True)))
    guard, notifier = guard_for(root, tail, fresh, done, free=GIB)

    assert await guard.check_once() is True

    stopped = read_state(tail)
    assert (stopped.floor_id, stopped.floor_reason, stopped.backfill.done) == (5, "disk", True)
    assert stopped.updated_at == NOW
    assert read_state(fresh).floor_id == 5
    assert read_state(done).floor_reason is None
    assert all(c.calls == ["pause_backfill"] for c in (tail, fresh, done))
    assert notifier.notes[0].level is Level.WARNING
    assert "stopped in 2 chat(s)" in notifier.notes[0].message
    assert "backfill --deeper" in notifier.notes[0].message


async def test_backfill_stop_skips_missing_or_unreadable_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    gone = FakeController(-9, root / "gone_-9")
    locked_chat = chat_in_tail(root, CHAT, oldest_done=5)
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == STATE_FILE:
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    guard, notifier = guard_for(root, gone, locked_chat, free=GIB)
    with caplog.at_level("WARNING"):
        await guard.check_once()
    monkeypatch.undo()
    assert read_state(locked_chat).backfill.done is False
    assert "cannot stop the backfill now" in caplog.text
    assert [n.message for n in notifier.notes] == [
        "space is low, everything allowed is already deleted"
    ]


async def test_floor_of_a_chat_without_parts_stays(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [])
    guard, _ = guard_for(root, chat, free=GIB)
    await guard.check_once()
    state = read_state(chat)
    assert (state.floor_id, state.backfill.done) == (0, True)


class Switch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")


async def test_media_gate_pauses_and_resumes(tmp_path: Path) -> None:
    switch = Switch()
    clock = FakeClock()
    disk = FakeDisk(14 * GIB, 16 * GIB, 17 * GIB)
    gate = MediaDiskGate(tmp_path, switch, DiskConfig(), disk=disk, clock=clock)
    for _ in range(3):
        gate.check_once()
    assert switch.calls == ["pause", "resume"]

    def stop(_: float) -> None:
        if len(clock.sleeps) >= 2:
            raise asyncio.CancelledError

    clock.on_sleep = stop
    with pytest.raises(asyncio.CancelledError):
        await gate.run()
    assert clock.sleeps == [300, 300]


def watcher_for(root: Path, chat: FakeController, confirm: int = 2) -> FolderWatcher:
    registry = ChatRegistry()
    registry.add(chat)
    return FolderWatcher(
        root,
        registry,
        WatchConfig(confirm_checks=confirm),
        clock=FakeClock(),
        notifier=RecordingNotifier(),
    )


async def test_state_read_permission_error_does_not_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(i, chat_id=CHAT)] for i in (1, 2)])
    list_parts(chat.folder)[0].unlink()
    before = (chat.folder / STATE_FILE).read_bytes()
    watcher = watcher_for(root, chat, confirm=1)
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == STATE_FILE:
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    for _ in range(3):
        await watcher.check_once()
    monkeypatch.undo()
    assert (chat.folder / STATE_FILE).read_bytes() == before


async def test_watcher_waits_for_stable_mismatch_before_recover(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(i, chat_id=CHAT)] for i in (1, 2, 3, 4)])
    watcher = watcher_for(root, chat)
    before = (chat.folder / STATE_FILE).read_bytes()
    parts = list_parts(chat.folder)

    parts[0].unlink()
    await watcher.check_once()
    assert (chat.folder / STATE_FILE).read_bytes() == before
    parts[1].unlink()
    await watcher.check_once()
    assert (chat.folder / STATE_FILE).read_bytes() == before
    await watcher.check_once()
    state = read_state(chat)
    assert sorted(state.chunks) == ["2026-09_003", "2026-09_004"]
    assert state.floor_id == 3


async def test_a_mismatch_that_heals_itself_resets_the_count(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(i, chat_id=CHAT)] for i in (1, 2)])
    watcher = watcher_for(root, chat)
    state = read_state(chat)
    extra = dict(state.chunks)
    extra["2026-08_001"] = ChunkInfo(1, 1, 1, 1)
    save_state(chat.folder, replace(state, chunks=extra))
    await watcher.check_once()
    save_state(chat.folder, state)
    await watcher.check_once()
    save_state(chat.folder, replace(state, chunks=extra))
    await watcher.check_once()
    assert "2026-08_001" in read_state(chat).chunks
    await watcher.check_once()
    assert "2026-08_001" not in read_state(chat).chunks
