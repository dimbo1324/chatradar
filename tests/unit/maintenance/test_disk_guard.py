from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from chatimport.config import DiskConfig
from chatimport.guards.disk import GIB, DiskGuard
from chatimport.runtime import ChatRegistry, Level
from chatimport.storage.layout import list_parts
from chatimport.trim import TrimmedPart, Trimmer
from tests.fakes import NOW, FakeClock, FakeDisk, RecordingNotifier
from tests.unit.maintenance.helpers import FakeController, build_chat, drive, message_ids

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.records import Record


class StubTrimmer:
    def __init__(self, parts: int = 0) -> None:
        self.remaining = parts
        self.calls: list[int] = []

    async def delete_oldest_part(self, protect_recent_days: int) -> TrimmedPart | None:
        self.calls.append(protect_recent_days)
        if self.remaining <= 0:
            return None
        self.remaining -= 1
        return TrimmedPart(1, "2026-01_001", 1, 1, 1, 10)


def build_guard(
    root: Path,
    trimmer: object,
    disk: object,
    *controllers: FakeController,
    config: DiskConfig | None = None,
    clock: FakeClock | None = None,
) -> tuple[DiskGuard, RecordingNotifier, ChatRegistry]:
    registry = ChatRegistry()
    for controller in controllers:
        registry.add(controller)
    notifier = RecordingNotifier()
    guard = DiskGuard(
        root,
        registry,
        cast("Trimmer", trimmer),
        config or DiskConfig(),
        clock=clock or FakeClock(),
        disk=cast("FakeDisk", disk),
        notifier=notifier,
    )
    return guard, notifier, registry


def ctl(tmp_path: Path, chat_id: int = 1, title: str = "Secret Title") -> FakeController:
    return FakeController(chat_id, tmp_path / f"chat_{chat_id}", title)


@pytest.mark.parametrize(
    ("free", "attempts"),
    [
        (15 * GIB, False),
        (15 * GIB + 1, False),
        (100 * GIB, False),
        (15 * GIB - 1, True),
        (0, True),
    ],
)
async def test_low_watermark_comparison_is_strict_at_exactly_15_gib(
    tmp_path: Path, free: int, attempts: bool
) -> None:
    trimmer = StubTrimmer(parts=0)
    controller = ctl(tmp_path)
    guard, notifier, _ = build_guard(tmp_path, trimmer, FakeDisk(free), controller)

    assert await guard.check_once() is attempts

    assert bool(trimmer.calls) is attempts
    assert (controller.calls == ["pause_backfill"]) is attempts
    assert bool(notifier.notes) is attempts


async def test_low_watermark_follows_the_configuration(tmp_path: Path) -> None:
    config = DiskConfig(low_watermark_gb=3, high_watermark_gb=4)
    trimmer = StubTrimmer(parts=0)
    guard, _, _ = build_guard(tmp_path, trimmer, FakeDisk(3 * GIB), config=config)
    assert await guard.check_once() is False
    guard, _, _ = build_guard(tmp_path, trimmer, FakeDisk(3 * GIB - 1), config=config)
    assert await guard.check_once() is True


@pytest.mark.parametrize(
    ("after_each", "deleted"),
    [
        ([15 * GIB, 16 * GIB, 17 * GIB], 3),
        ([17 * GIB - 1, 17 * GIB], 2),
        ([17 * GIB], 1),
    ],
)
async def test_trimming_continues_until_free_space_reaches_17_gib_inclusive(
    tmp_path: Path, after_each: list[int], deleted: int
) -> None:
    trimmer = StubTrimmer(parts=50)
    disk = FakeDisk(14 * GIB, *after_each)
    guard, notifier, _ = build_guard(tmp_path, trimmer, disk)

    assert await guard.check_once() is True

    assert len(trimmer.calls) == deleted
    assert disk.calls == 1 + deleted
    assert [n.level for n in notifier.notes] == [Level.INFO]
    assert f"deleted {deleted} parts" in notifier.notes[0].message


async def test_hysteresis_does_not_run_between_the_watermarks(tmp_path: Path) -> None:
    trimmer = StubTrimmer(parts=5)
    guard, _, _ = build_guard(tmp_path, trimmer, FakeDisk(16 * GIB))

    assert await guard.check_once() is False
    assert trimmer.calls == []


async def test_after_a_trim_cycle_the_guard_stays_quiet_until_below_the_low_mark_again(
    tmp_path: Path,
) -> None:
    trimmer = StubTrimmer(parts=5)
    disk = FakeDisk(14 * GIB, 17 * GIB, 16 * GIB, 14 * GIB, 17 * GIB)
    guard, _, _ = build_guard(tmp_path, trimmer, disk)

    assert await guard.check_once() is True
    assert await guard.check_once() is False
    assert await guard.check_once() is True
    assert len(trimmer.calls) == 2


async def test_nothing_deletable_warns_once_and_stops_instead_of_looping(
    tmp_path: Path,
) -> None:
    trimmer = StubTrimmer(parts=0)
    disk = FakeDisk(1 * GIB)
    guard, notifier, _ = build_guard(tmp_path, trimmer, disk)

    assert await asyncio.wait_for(guard.check_once(), timeout=5) is True

    assert len(trimmer.calls) == 1
    assert [(n.level, n.title) for n in notifier.notes] == [(Level.WARNING, "Disk space")]
    assert "already deleted" in notifier.notes[0].message


async def test_partial_success_then_exhaustion_reports_both(tmp_path: Path) -> None:
    trimmer = StubTrimmer(parts=2)
    disk = FakeDisk(10 * GIB, 11 * GIB, 12 * GIB)
    guard, notifier, _ = build_guard(tmp_path, trimmer, disk)

    await guard.check_once()

    assert len(trimmer.calls) == 3
    assert [n.level for n in notifier.notes] == [Level.WARNING, Level.INFO]
    assert notifier.notes[1].message == "freed 2.0 GB: deleted 2 parts"


async def test_freed_amount_is_never_negative(tmp_path: Path) -> None:
    trimmer = StubTrimmer(parts=1)
    disk = FakeDisk(10 * GIB, 9 * GIB, 9 * GIB)
    guard, notifier, _ = build_guard(tmp_path, trimmer, disk)

    await guard.check_once()

    info = [n for n in notifier.notes if n.level is Level.INFO]
    assert info[0].message == "freed 0.0 GB: deleted 1 parts"


async def test_every_controller_backfill_is_paused_and_never_resumed(tmp_path: Path) -> None:
    controllers = [ctl(tmp_path, i) for i in (1, 2, 3)]
    trimmer = StubTrimmer(parts=1)
    disk = FakeDisk(1 * GIB, 20 * GIB)
    guard, _, _ = build_guard(tmp_path, trimmer, disk, *controllers)

    await guard.check_once()

    assert [c.calls for c in controllers] == [["pause_backfill"]] * 3


async def test_notifications_carry_no_chat_names(tmp_path: Path) -> None:
    controller = ctl(tmp_path, 5, "Very Private Group")
    trimmer = StubTrimmer(parts=1)
    guard, notifier, _ = build_guard(
        tmp_path, trimmer, FakeDisk(1 * GIB, 20 * GIB, 20 * GIB), controller
    )

    await guard.check_once()
    trimmer.remaining = 0
    guard2, notifier2, _ = build_guard(tmp_path, trimmer, FakeDisk(1 * GIB), controller)
    await guard2.check_once()

    text = " ".join(f"{n.title} {n.message}" for n in notifier.notes + notifier2.notes)
    assert "Private" not in text
    assert "Group" not in text


async def test_protect_recent_days_is_passed_to_the_trimmer(tmp_path: Path) -> None:
    trimmer = StubTrimmer(parts=0)
    guard, _, _ = build_guard(
        tmp_path, trimmer, FakeDisk(1 * GIB), config=DiskConfig(protect_recent_days=45)
    )

    await guard.check_once()

    assert trimmer.calls == [45]


async def test_run_checks_every_configured_interval(tmp_path: Path) -> None:
    clock = FakeClock()
    disk = FakeDisk(100 * GIB)
    guard, _, _ = build_guard(
        tmp_path,
        StubTrimmer(),
        disk,
        config=DiskConfig(check_every_minutes=7),
        clock=clock,
    )

    await drive(guard.run, clock, cycles=3)

    assert clock.sleeps == [420.0, 420.0, 420.0]
    assert disk.calls == 3


@dataclass
class ExplodingDisk:
    fail_times: int
    calls: int = 0

    def free_bytes(self, path: Path) -> int:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OSError("volume vanished")
        return 100 * GIB


async def test_an_exception_in_one_iteration_does_not_kill_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    disk = ExplodingDisk(fail_times=2)
    guard, _, _ = build_guard(tmp_path, StubTrimmer(), disk, clock=clock)

    with caplog.at_level("ERROR"):
        await drive(guard.run, clock, cycles=4)

    assert disk.calls == 4
    assert caplog.text.count("disk guard check failed") == 2


async def test_cancellation_of_run_is_not_swallowed(tmp_path: Path) -> None:
    clock = FakeClock()
    guard, _, _ = build_guard(tmp_path, StubTrimmer(), FakeDisk(100 * GIB), clock=clock)

    task = asyncio.create_task(guard.run())
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


class GrowingDisk:
    """Free space grows by 1 GiB for every part file that disappeared from the folders."""

    def __init__(self, folders: list[Path], start: int, parts: int) -> None:
        self._folders = folders
        self._start = start
        self._parts = parts

    def free_bytes(self, path: Path) -> int:
        now = sum(len(list_parts(f)) for f in self._folders)
        return self._start + (self._parts - now) * GIB


async def test_with_the_real_trimmer_the_oldest_parts_go_first_until_17_gib(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"

    def parts(chat_id: int, months: list[int]) -> list[list[Record]]:
        from chatimport.records import MessageRecord
        from tests.unit.maintenance.helpers import at

        return [
            [MessageRecord(chat_id, i, at(2026, month, 2), NOW, text="x")]
            for i, month in enumerate(months, start=1)
        ]

    a = build_chat(root, -1, parts(-1, [1, 3, 5]), title="A")
    b = build_chat(root, -2, parts(-2, [2, 4, 6]), title="B")
    registry = ChatRegistry()
    registry.add(a)
    registry.add(b)
    trimmer = Trimmer(root, registry, clock=FakeClock(), max_chunk_bytes=1)
    disk = GrowingDisk([a.folder, b.folder], start=int(14.5 * GIB), parts=6)
    notifier = RecordingNotifier()
    guard = DiskGuard(
        root,
        registry,
        trimmer,
        DiskConfig(protect_recent_days=30),
        clock=FakeClock(),
        disk=disk,
        notifier=notifier,
    )

    assert await guard.check_once() is True

    assert message_ids(a) == [3]
    assert message_ids(b) == [2, 3]
    assert a.calls == ["pause_backfill"]
    assert [n.level for n in notifier.notes] == [Level.INFO]
    assert "deleted 3 parts" in notifier.notes[0].message
    assert (root / "_trim_log.jsonl").read_text(encoding="utf-8").count("\n") == 3


async def test_with_the_real_trimmer_recent_parts_are_never_deleted(tmp_path: Path) -> None:
    from chatimport.records import MessageRecord
    from tests.unit.maintenance.helpers import at

    root = tmp_path / "root"
    recent = [[MessageRecord(-1, 1, at(2026, 10, 20), NOW, text="x")]]
    chat = build_chat(root, -1, recent, title="A")
    registry = ChatRegistry()
    registry.add(chat)
    notifier = RecordingNotifier()
    guard = DiskGuard(
        root,
        registry,
        Trimmer(root, registry, clock=FakeClock(), max_chunk_bytes=1),
        DiskConfig(),
        clock=FakeClock(),
        disk=FakeDisk(GIB),
        notifier=notifier,
    )

    await guard.check_once()

    assert message_ids(chat) == [1]
    assert [n.level for n in notifier.notes] == [Level.WARNING]
