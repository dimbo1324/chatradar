"""Less common paths of the chat worker: failing final flush, a paused tail, odd part files."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.ports import AccessLost
from chatimport.records import EditRecord
from chatimport.storage.state import save_state
from chatimport.storage.writer import ChunkWriter
from chatimport.storage.writer import iter_part_records as real_iter_part_records
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.worker.rig import (
    RigFactory,
    assert_disk_consistent,
    make_rig,
    new_event,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from chatimport.records import Record

__all__ = ["make_rig"]


def tail_calls(gateway: Any) -> list[tuple[Any, ...]]:
    return [args for name, args in gateway.calls if name == "iter_history" and args[1]]


async def test_a_failing_final_flush_is_logged_and_does_not_mask_the_original_error(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    rig = make_rig(range(1, 101))
    rig.start()
    await rig.until_complete()

    def broken(folder: Path, state: Any) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr("chatimport.storage.writer.save_state", broken)
    monkeypatch.setattr("chatimport.storage.recover.save_state", broken)
    for i in range(101, 106):
        rig.worker.submit(new_event(i))
    assert rig.task is not None
    with (
        caplog.at_level(logging.ERROR, logger="chatimport.worker"),
        pytest.raises(PermissionError, match="locked"),
    ):
        await asyncio.wait_for(rig.task, 3)

    assert any("final flush failed" in r.getMessage() for r in caplog.records)
    assert rig.worker.status().error == "PermissionError"


async def test_a_backfill_paused_in_the_middle_of_the_tail_waits_and_then_continues(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    seen = 0

    def hook() -> None:
        nonlocal seen
        if tail_calls(rig.gateway):
            seen += 1
            if seen == 5:
                rig.worker.pause_backfill()

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until_live()
    await rig.settle()
    assert not rig.backfill_done()
    assert seen == 5

    rig.worker.resume_backfill()
    await rig.until_complete()
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_refetch_requested_during_the_tail_restarts_from_the_head(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    seen = 0

    def hook() -> None:
        nonlocal seen
        if tail_calls(rig.gateway):
            seen += 1
            if seen == 5:
                shutil.rmtree(rig.folder)
                rig.worker.request_refetch()

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until(
        lambda: seen >= 5 and rig.is_live() and rig.backfill_done() and len(rig.ids()) == 1000,
        "refetched",
    )

    assert rig.gateway.count("newest_id") == 2
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_reconcile_does_not_start_a_second_tail_while_one_is_waiting(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    rig.worker.pause_backfill()
    rig.start()
    await rig.until_live()
    await rig.settle()
    assert len(tail_calls(rig.gateway)) == 1

    rig.clock.advance(seconds=601)
    rig.worker.resume()
    await rig.settle()

    assert len(tail_calls(rig.gateway)) == 1
    rig.worker.resume_backfill()
    await rig.until_complete()
    assert len(tail_calls(rig.gateway)) == 1
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_catch_up_ignores_messages_at_or_below_the_floor(make_rig: RigFactory) -> None:
    first = make_rig(range(1, 51))
    first.start()
    await first.until_complete()
    await first.shutdown()
    save_state(first.folder, replace(first.state(), floor_id=60))
    for i in range(51, 56):
        first.gateway.chats[CHAT_ID][i] = msg(i)

    second = make_rig(gateway=first.gateway, clock=first.clock)
    mark = len(first.gateway.calls)
    second.start()
    await second.until(
        lambda: first.gateway.count("iter_since") > 1 and second.is_live(), "caught up"
    )
    await second.settle()

    assert second.state().last_id == 50
    assert second.ids() == list(range(1, 51))
    assert ("iter_since", (CHAT_ID, 50)) in first.gateway.calls[mark:]


async def test_lost_access_while_the_state_file_vanishes_is_still_reported(
    make_rig: RigFactory,
) -> None:
    first = make_rig(range(1, 51))
    first.start()
    await first.until_complete()
    await first.shutdown()
    for i in range(51, 56):
        first.gateway.chats[CHAT_ID][i] = msg(i)

    def hook() -> None:
        (first.folder / "state.json").unlink(missing_ok=True)
        raise AccessLost(CHAT_ID)

    first.gateway.page_hook = hook
    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.until(lambda: second.worker.status().error == "no access", "no access")

    assert [n.message for n in second.notifier.notes] == ["No access to the chat; data kept"]


async def test_oldest_date_skips_parts_that_hold_no_messages(make_rig: RigFactory) -> None:
    first = make_rig(range(1, 21))
    first.start()
    await first.until_complete()
    await first.shutdown()
    early_edit = EditRecord(CHAT_ID, 5, datetime(2026, 1, 5, tzinfo=UTC), NOW, "old", None)
    ChunkWriter(first.folder, 10**9, lambda: NOW).append(first.state(), [early_edit])
    assert (first.folder / "2026-01_001.jsonl").is_file()

    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.settle(600)

    assert second.worker.status().oldest_date == msg(1).date


async def test_an_unreadable_part_does_not_break_the_oldest_date_lookup(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    failures = [OSError("locked by antivirus")]

    def flaky(path: Path) -> Iterator[Record]:
        if failures:
            raise failures.pop()
        return real_iter_part_records(path)

    rig = make_rig(range(1, 1001))
    monkeypatch.setattr("chatimport.worker.iter_part_records", flaky)
    rig.start()

    await rig.until_complete()

    assert rig.worker.status().oldest_date is not None
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))
