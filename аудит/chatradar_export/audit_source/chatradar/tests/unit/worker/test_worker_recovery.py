"""The worker keeps the owner's data and choices across refetches, restarts, lost access,
unreadable state files and changes made by other components."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.offline import lower_floor_state
from chatimport.ports import AccessLost
from chatimport.records import DeleteRecord, EditRecord, MessageRecord
from chatimport.runtime import ChatRegistry
from chatimport.storage.layout import list_parts
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import (
    PHASE_NO_ACCESS,
    PHASE_PAUSED,
    StateUnreadable,
    load_state,
    save_state,
)
from chatimport.storage.writer import iter_part_records, iter_records
from chatimport.trim import Trimmer
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.worker.rig import (
    Rig,
    RigFactory,
    assert_disk_consistent,
    delete_event,
    edit_event,
    make_rig,
    new_event,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["make_rig"]


async def live_rig(make_rig: RigFactory, ids: range = range(1, 401), **kwargs: Any) -> Rig:
    rig = make_rig(ids, **kwargs)
    rig.start()
    await rig.until_complete()
    return rig


def tail_calls(rig: Rig) -> list[tuple[Any, ...]]:
    return tail_calls_since(rig, 0)


def tail_calls_since(rig: Rig, mark: int) -> list[tuple[Any, ...]]:
    return [args for name, args in rig.gateway.calls[mark:] if name == "iter_history" and args[1]]


def drop_parts_below(folder: Path, msg_id: int) -> None:
    for part in list_parts(folder):
        ids = [r.msg_id for r in iter_part_records(part) if isinstance(r, MessageRecord)]
        if ids and max(ids) < msg_id:
            part.unlink()


async def test_a_refetch_over_an_existing_folder_keeps_the_current_month_history(
    make_rig: RigFactory,
) -> None:
    first = await live_rig(make_rig)
    first.worker.submit(edit_event(399, "edited"))
    first.worker.submit(delete_event([398]))
    await first.worker.stop()
    del first.gateway.chats[CHAT_ID][398]
    rig = make_rig(gateway=first.gateway, clock=first.clock)
    rig.start()
    await rig.until_live()

    rig.worker.request_refetch()
    await rig.until(lambda: rig.gateway.count("newest_id") == 2, "head backfill again")
    await rig.until_complete()

    records = list(iter_records(rig.folder))
    assert [r.msg_id for r in records if isinstance(r, EditRecord)] == [399]
    assert [r.msg_ids for r in records if isinstance(r, DeleteRecord)] == [(398,)]
    assert 398 in rig.ids()
    state = rig.state()
    assert (state.floor_id, state.backfill.done) == (0, True)
    assert_disk_consistent(rig.folder, expect_ids=range(1, 401))


async def test_a_refetch_over_a_trimmed_folder_brings_the_old_history_back(
    make_rig: RigFactory,
) -> None:
    first = await live_rig(make_rig, range(1, 1001))
    await first.worker.stop()
    for part in list_parts(first.folder)[:3]:
        part.unlink()
    rig = make_rig(gateway=first.gateway, clock=first.clock)
    rig.start()
    await rig.until_live()

    rig.worker.request_refetch()
    await rig.until(lambda: rig.gateway.count("newest_id") == 2, "head backfill again")
    await rig.until_complete()

    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_pause_survives_a_restart(make_rig: RigFactory) -> None:
    first = await live_rig(make_rig, range(1, 51))
    first.worker.pause()
    await first.until(lambda: first.phase() == PHASE_PAUSED, "parked")
    await first.worker.stop()
    assert first.phase() == PHASE_PAUSED
    first.gateway.chats[CHAT_ID][51] = msg(51)
    mark = len(first.gateway.calls)

    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.settle()

    assert second.phase() == PHASE_PAUSED
    assert second.worker.status().paused
    assert [name for name, _ in first.gateway.calls[mark:]] == []
    second.worker.resume()
    await second.until(lambda: second.is_live() and 51 in second.ids(), "caught up")


async def test_an_explicit_resume_before_start_overrides_the_stored_pause(
    make_rig: RigFactory,
) -> None:
    first = await live_rig(make_rig, range(1, 51))
    first.worker.pause()
    await first.until(lambda: first.phase() == PHASE_PAUSED, "parked")
    await first.worker.stop()

    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.worker.resume()
    second.start()
    await second.until_live()
    assert not second.worker.status().paused


async def test_no_access_is_retried_after_a_growing_delay(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 51))
    rig.gateway.fail["newest_id"] = [AccessLost(CHAT_ID), AccessLost(CHAT_ID)]
    rig.start()
    await rig.until(lambda: rig.gateway.count("newest_id") == 1, "first attempt")
    await rig.until(lambda: rig.phase() == PHASE_NO_ACCESS, "no access")

    rig.clock.advance(seconds=59)
    rig.worker.resume()
    await rig.settle()
    assert rig.gateway.count("newest_id") == 1

    rig.clock.advance(seconds=1)
    rig.worker.resume()
    await rig.until(lambda: rig.gateway.count("newest_id") == 2, "first retry")
    await rig.until(lambda: rig.worker.status().error == "no access", "still no access")

    rig.clock.advance(seconds=119)
    rig.worker.resume()
    await rig.settle()
    assert rig.gateway.count("newest_id") == 2

    rig.clock.advance(seconds=1)
    rig.worker.resume()
    await rig.until_complete()
    assert rig.worker.status().error is None
    assert_disk_consistent(rig.folder, expect_ids=range(1, 51))


async def test_status_reflects_a_trim_at_once(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig, range(1, 1001))
    before = rig.worker.status()
    registry = ChatRegistry()
    registry.add(rig.worker)
    trimmer = Trimmer(rig.root, registry, clock=rig.clock, max_chunk_bytes=10**9)

    await trimmer.trim_percent(50, CHAT_ID)

    after = rig.worker.status()
    state = rig.state()
    assert after.records == state.total_records < before.records
    assert before.oldest_date is not None
    assert after.oldest_date is not None
    assert after.oldest_date > before.oldest_date
    first = next(
        r
        for r in iter_part_records(rig.folder / f"{min(state.chunks)}.jsonl")
        if isinstance(r, MessageRecord)
    )
    assert after.oldest_date == first.date


async def test_an_unreadable_state_file_is_waited_out_and_never_rebuilt_over(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await live_rig(make_rig, range(1, 51))
    folder = rig.folder
    save_state(folder, replace(rig.state(), floor_id=7, floor_reason="manual_trim_25"))
    failures = [StateUnreadable(folder, PermissionError("sharing violation")) for _ in range(3)]
    real = load_state

    def flaky(path: Path) -> Any:
        if failures:
            raise failures.pop()
        return real(path)

    monkeypatch.setattr("chatimport.storage.chat_store.load_state", flaky)
    monkeypatch.setattr("chatimport.storage.recover.load_state", flaky)
    for i in range(51, 56):
        rig.gateway.chats[CHAT_ID][i] = msg(i)
    status = rig.worker.status()
    assert status.last_id == 50

    rig.clock.advance(seconds=601)
    rig.worker.resume()
    await rig.until(lambda: rig.is_live() and max(rig.ids()) == 55, "back after the failures")

    assert rig.task is not None
    assert not rig.task.done()
    assert failures == []
    assert 20 in rig.clock.sleeps
    state = rig.state()
    assert (state.floor_id, state.floor_reason) == (7, "manual_trim_25")


async def test_the_folder_stays_put_while_it_exists(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig, range(1, 11))
    real = rig.folder
    decoy = real.with_name(f"Decoy_{CHAT_ID}")
    shutil.copytree(real, decoy)
    (real / "state.json").unlink()

    assert rig.worker.folder == real


async def test_a_late_older_message_is_kept_in_id_order(make_rig: RigFactory) -> None:
    first = await live_rig(make_rig)
    for i in (401, 402, 403, 405):
        first.worker.submit(new_event(i))
    await first.worker.stop()
    rig = make_rig(gateway=first.gateway, clock=first.clock)
    rig.start()
    await rig.until_live()

    rig.worker.submit(new_event(404))
    rig.worker.submit(new_event(400, text="replayed"))
    await rig.worker.stop()

    ids = assert_disk_consistent(rig.folder, expect_ids=range(1, 406))
    assert ids[-6:] == [400, 401, 402, 403, 404, 405]
    stored_400 = [r for r in iter_records(rig.folder) if getattr(r, "msg_id", 0) == 400]
    assert [r.text for r in stored_400 if isinstance(r, MessageRecord)] == ["text 400"]


async def test_a_late_message_in_a_flush_with_new_ones_lands_in_its_month(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)
    for i in range(401, 406):
        rig.worker.submit(new_event(i))
    await rig.until(lambda: max(rig.ids()) == 405, "first flush")
    rig.worker.submit(new_event(406))
    rig.worker.submit(new_event(380, date=NOW - timedelta(days=200)))
    await rig.worker.stop()

    assert 380 in rig.ids()


async def test_deeper_after_a_finished_backfill_starts_the_tail_at_once(
    make_rig: RigFactory,
) -> None:
    first = await live_rig(make_rig, range(1, 1001))
    await first.worker.stop()
    drop_parts_below(first.folder, 500)
    state = recover_chat(first.folder, now=NOW)
    save_state(first.folder, replace(state, floor_id=500, floor_reason="manual_trim_50"))
    rig = make_rig(gateway=first.gateway, clock=first.clock)
    rig.start()
    await rig.until_live()
    calls = len(tail_calls(rig))

    async with rig.worker.lock:
        assert lower_floor_state(rig.folder, rig.clock.now())
    rig.worker.resume_backfill()
    await rig.until_complete()

    assert len(tail_calls(rig)) == calls + 1
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_deeper_while_a_tail_runs_lowers_its_target(make_rig: RigFactory) -> None:
    first = await live_rig(make_rig, range(1, 1001))
    await first.worker.stop()
    drop_parts_below(first.folder, 600)
    state = recover_chat(first.folder, now=NOW)
    backfill = replace(state.backfill, done=False, oldest_done_id=600)
    save_state(
        first.folder,
        replace(state, floor_id=500, floor_reason="manual_trim_50", backfill=backfill),
    )
    rig = make_rig(gateway=first.gateway, clock=first.clock)
    mark = len(first.gateway.calls)
    seen = 0

    def hook() -> None:
        nonlocal seen
        if not tail_calls_since(rig, mark):
            return
        seen += 1
        if seen == 10:
            assert lower_floor_state(rig.folder, rig.clock.now())
            rig.worker.resume_backfill()

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until_complete()

    assert tail_calls_since(rig, mark)[0][1:] == (600, 500)
    assert rig.state().floor_id == 0
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_tail_flushes_a_large_month_in_pieces(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chatimport.worker_backfill.TAIL_FLUSH_RECORDS", 3)
    rig = make_rig(range(1, 1001))
    progress: list[int] = []

    def hook() -> None:
        if tail_calls(rig):
            state = load_state(rig.folder)
            if state is not None and (
                not progress or progress[-1] != state.backfill.oldest_done_id
            ):
                progress.append(state.backfill.oldest_done_id)

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until_complete()

    assert len(progress) > 100
    assert progress == sorted(progress, reverse=True)
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_paused_worker_keeps_its_queue_bounded_and_catches_up_on_resume(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await live_rig(make_rig)
    monkeypatch.setattr(rig.worker._intake.buffer, "capacity", 50)  # pyright: ignore[reportPrivateUsage]
    rig.worker.pause()
    await rig.until(lambda: rig.phase() == PHASE_PAUSED, "parked")
    for i in range(401, 1401):
        rig.gateway.chats[CHAT_ID][i] = msg(i, date=NOW)
        rig.worker.submit(new_event(i, date=NOW))

    assert rig.worker._intake.queue.qsize() <= 51  # pyright: ignore[reportPrivateUsage]
    rig.worker.resume()
    await rig.until(lambda: rig.is_live() and max(rig.ids()) == 1400, "caught up")
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1401), ordered=False)


async def test_failing_flushes_keep_the_buffer_bounded_and_catch_up_afterwards(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await live_rig(make_rig)
    worker = rig.worker
    monkeypatch.setattr(worker._intake.buffer, "capacity", 20)  # pyright: ignore[reportPrivateUsage]
    failures = [OSError("disk full")]

    def flaky(folder: Path, state: Any) -> None:
        if failures:
            raise failures.pop()
        save_state(folder, state)

    monkeypatch.setattr("chatimport.storage.writer.save_state", flaky)
    for i in range(401, 461):
        rig.gateway.chats[CHAT_ID][i] = msg(i, date=NOW)
        worker.submit(new_event(i, date=NOW))
    assert rig.task is not None
    with pytest.raises(OSError, match="disk full"):
        await asyncio.wait_for(rig.task, 3)
    pending = len(worker._intake.buffer) + worker._intake.queue.qsize()  # pyright: ignore[reportPrivateUsage]
    assert pending <= 20

    rig.start()
    await rig.until(
        lambda: rig.is_live() and rig.state().last_recheck_at is not None, "caught up, rechecked"
    )
    assert_disk_consistent(rig.folder, expect_ids=range(1, 461), ordered=False)


async def test_the_live_loop_sleeps_until_its_next_deadline(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await live_rig(make_rig)
    await rig.settle()
    timeouts: list[float] = []
    real = asyncio.wait_for

    async def recording(awaitable: Any, limit: float | None) -> Any:
        timeouts.append(-1.0 if limit is None else limit)
        return await real(awaitable, limit)

    monkeypatch.setattr("chatimport.worker_live.asyncio.wait_for", recording)
    rig.worker.resume()
    await rig.settle()
    rig.worker.submit(new_event(401))
    await rig.settle()

    assert timeouts[0] > 500
    assert timeouts[-1] == pytest.approx(30.0)
    assert len(timeouts) == 2


async def test_a_backfill_stopped_by_the_disk_guard_is_never_reopened_by_the_tail(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    stopped_at: list[int] = []

    def hook() -> None:
        if len(tail_calls(rig)) == 1 and not stopped_at:
            state = rig.state()
            done_id = state.backfill.oldest_done_id
            stopped_at.append(done_id)
            backfill = replace(state.backfill, done=True)
            save_state(
                rig.folder,
                replace(state, floor_id=done_id, floor_reason="disk", backfill=backfill),
            )

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until(lambda: bool(stopped_at) and rig.backfill_done(), "stopped")
    await rig.settle()

    state = rig.state()
    assert (state.floor_id, state.floor_reason) == (stopped_at[0], "disk")
    assert state.backfill.done
    assert min(rig.ids()) == stopped_at[0]


async def test_lost_access_with_an_unreadable_state_file_is_still_reported(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = make_rig(range(1, 51))
    unreadable = False
    real = load_state

    def flaky(path: Path) -> Any:
        if unreadable:
            raise StateUnreadable(path, PermissionError("locked"))
        return real(path)

    def hook() -> None:
        nonlocal unreadable
        unreadable = True
        raise AccessLost(CHAT_ID)

    monkeypatch.setattr("chatimport.storage.chat_store.load_state", flaky)
    rig.gateway.page_hook = hook
    rig.start()
    await rig.until(lambda: rig.worker.status().error == "no access", "no access")

    assert [n.message for n in rig.notifier.notes] == ["No access to the chat; data kept"]
