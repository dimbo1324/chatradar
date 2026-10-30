"""Live phase of the chat worker: buffering, flushing, events, reconcile, pause, stop."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.ports import ChatEvent, EditedMessageEvent
from chatimport.records import (
    DETECTED_EVENT,
    DeleteRecord,
    EditRecord,
    MessageRecord,
    Record,
)
from chatimport.storage.layout import list_parts
from chatimport.storage.state import PHASE_LIVE, PHASE_PAUSED, PHASE_RECOVER, save_state
from chatimport.storage.writer import iter_part_records, iter_records
from tests.fakes import CHAT_ID, FakeGateway, msg
from tests.unit.worker.rig import (
    Rig,
    RigFactory,
    assert_disk_consistent,
    delete_event,
    edit_event,
    make_config,
    make_rig,
    new_event,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["make_rig"]


class HangingGateway(FakeGateway):
    async def newest_id(self, chat_id: int) -> int:
        await asyncio.Event().wait()
        return 0


async def live_rig(make_rig: RigFactory, ids: range = range(1, 401), **kwargs: Any) -> Rig:
    rig = make_rig(ids, **kwargs)
    rig.start()
    await rig.until_complete()
    return rig


def submit(rig: Rig, *events: ChatEvent) -> None:
    for event in events:
        rig.worker.submit(event)


def records_on_disk(folder: Path) -> list[Record]:
    return list(iter_records(folder))


def at(msg_id: int, iso: str, **kwargs: Any) -> MessageRecord:
    return msg(msg_id, date=datetime.fromisoformat(iso), **kwargs)


async def test_flush_waits_for_the_fifth_buffered_event(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)

    submit(rig, *(new_event(i) for i in range(401, 405)))
    await rig.settle()
    assert max(rig.ids()) == 400

    submit(rig, new_event(405))
    await rig.until(lambda: max(rig.ids()) == 405, "flush by count")

    assert rig.state().last_id == 405
    assert_disk_consistent(rig.folder, expect_ids=range(1, 406))


@pytest.mark.parametrize(
    ("elapsed", "flushed"),
    [(29, False), (29.999, False), (30, True), (45, True)],
)
async def test_flush_by_time_counts_from_the_first_buffered_event(
    make_rig: RigFactory, elapsed: float, flushed: bool
) -> None:
    rig = await live_rig(make_rig)
    submit(rig, new_event(401), new_event(402))
    await rig.settle()

    rig.clock.advance(seconds=elapsed)
    rig.worker.resume()
    await rig.settle()

    assert (max(rig.ids()) == 402) is flushed
    if flushed:
        assert_disk_consistent(rig.folder, expect_ids=range(1, 403))


async def test_the_flush_timer_is_not_restarted_by_later_events(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)
    submit(rig, new_event(401))
    await rig.settle()
    rig.clock.advance(seconds=20)
    submit(rig, new_event(402))
    await rig.settle()
    assert max(rig.ids()) == 400

    rig.clock.advance(seconds=11)
    rig.worker.resume()
    await rig.until(lambda: max(rig.ids()) == 402, "flush 31 s after the first event")


async def test_a_flushed_buffer_starts_a_fresh_timer(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)
    submit(rig, new_event(401))
    await rig.settle()
    rig.clock.advance(seconds=31)
    rig.worker.resume()
    await rig.until(lambda: max(rig.ids()) == 401, "first flush")

    submit(rig, new_event(402))
    await rig.settle()
    rig.clock.advance(seconds=29)
    rig.worker.resume()
    await rig.settle()
    assert max(rig.ids()) == 401


async def test_events_out_of_order_and_replayed_are_written_once_in_id_order(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)

    submit(
        rig,
        new_event(405),
        new_event(401),
        new_event(399),
        new_event(403),
        new_event(401, text="replay of 401"),
        new_event(402),
        new_event(404),
    )
    await rig.until(lambda: max(rig.ids()) == 405, "flush")

    ids = assert_disk_consistent(rig.folder, expect_ids=range(1, 406))
    assert ids[-6:] == [400, 401, 402, 403, 404, 405]
    first_401 = next(r for r in records_on_disk(rig.folder) if getattr(r, "msg_id", 0) == 401)
    assert isinstance(first_401, MessageRecord)
    assert first_401.text == "text 401"


async def test_replayed_events_of_already_stored_messages_change_nothing(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)
    before = {p.name: p.read_bytes() for p in list_parts(rig.folder)}

    submit(rig, *(new_event(i) for i in (400, 399, 398, 1, 2)))
    await rig.settle()

    assert {p.name: p.read_bytes() for p in list_parts(rig.folder)} == before
    assert_disk_consistent(rig.folder, expect_ids=range(1, 401))


async def test_a_batch_crossing_midnight_utc_is_split_into_month_files(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)

    for record in (
        at(1001, "2026-10-31T23:59:59+00:00"),
        at(1002, "2026-11-01T00:00:00+00:00"),
        at(1003, "2026-11-01T00:00:01+00:00"),
        at(1004, "2026-11-02T10:00:00+00:00"),
        at(1005, "2026-11-01T02:59:59+03:00"),
    ):
        rig.worker.submit(new_event(record.msg_id, date=record.date))
    await rig.until(lambda: rig.state().last_id == 1005, "flush")

    parts = {
        p.stem: [r.msg_id for r in iter_part_records(p) if isinstance(r, MessageRecord)]
        for p in list_parts(rig.folder)
    }
    assert parts["2026-11_001"] == [1002, 1003, 1004]
    assert parts["2026-10_001"][-2:] == [1001, 1005]
    assert_disk_consistent(rig.folder, ordered=False)


async def test_edit_goes_to_the_month_of_its_edit_date_and_does_not_move_last_id(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)
    edit_date = datetime(2026, 11, 5, 10, 0, 0, tzinfo=UTC)

    submit(
        rig,
        edit_event(10, "edited", edit_date),
        edit_event(11, "late edit", datetime(2026, 11, 5, 11, 0, 0, tzinfo=UTC)),
    )
    rig.worker.resume()
    await rig.worker.stop()

    november = list(iter_part_records(rig.folder / "2026-11_001.jsonl"))
    assert [type(r) for r in november] == [EditRecord, EditRecord]
    first = november[0]
    assert isinstance(first, EditRecord)
    assert (first.msg_id, first.text, first.edit_date) == (10, "edited", edit_date)
    assert first.detected_by == DETECTED_EVENT
    assert rig.state().last_id == 400
    chunk = rig.state().chunks["2026-11_001"]
    assert (chunk.records, chunk.first_id, chunk.last_id) == (2, 0, 0)
    assert_disk_consistent(rig.folder, expect_ids=range(1, 401))


async def test_an_edit_event_without_edit_date_falls_back_to_fetch_time(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)
    fetched = datetime(2026, 12, 3, 4, 5, 6, tzinfo=UTC)

    submit(rig, EditedMessageEvent(msg(10, text="y", fetched_at=fetched, edit_date=None)))
    await rig.worker.stop()

    edits = [r for r in records_on_disk(rig.folder) if isinstance(r, EditRecord)]
    assert [e.edit_date for e in edits] == [fetched]


@pytest.mark.parametrize(
    ("track_edits", "track_deletes", "kinds"),
    [
        (True, True, ["edit", "delete"]),
        (False, True, ["delete"]),
        (True, False, ["edit"]),
        (False, False, []),
    ],
)
async def test_event_tracking_toggles_drop_only_the_disabled_kind(
    make_rig: RigFactory, track_edits: bool, track_deletes: bool, kinds: list[str]
) -> None:
    config = make_config(events={"track_edits": track_edits, "track_deletes": track_deletes})
    rig = await live_rig(make_rig, config=config)

    submit(rig, edit_event(10, "new"), delete_event([11]), new_event(401))
    await rig.worker.stop()

    extra = [r.kind for r in records_on_disk(rig.folder) if r.kind != "message"]
    assert sorted(extra) == sorted(kinds)
    assert 401 in rig.ids()


async def test_delete_events_for_other_chats_or_without_chat_id_are_ignored(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)

    submit(
        rig,
        delete_event([1], None),
        delete_event([2], CHAT_ID + 1),
        delete_event([3], -CHAT_ID),
        new_event(401),
        new_event(402),
    )
    await rig.until(lambda: max(rig.ids()) == 402, "flush")

    assert [r for r in records_on_disk(rig.folder) if isinstance(r, DeleteRecord)] == []


async def test_delete_event_is_stored_with_its_ids_and_detection_source(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)

    submit(rig, delete_event([5, 3, 9]))
    await rig.worker.stop()

    deletes = [r for r in records_on_disk(rig.folder) if isinstance(r, DeleteRecord)]
    assert len(deletes) == 1
    assert deletes[0].msg_ids == (5, 3, 9)
    assert deletes[0].detected_by == DETECTED_EVENT
    assert deletes[0].fetched_at == rig.clock.now()
    assert rig.state().last_id == 400


async def test_events_at_or_below_the_floor_are_dropped_but_the_floor_message_is_kept(
    make_rig: RigFactory,
) -> None:
    first = await live_rig(make_rig)
    await first.shutdown()
    save_state(first.folder, replace(first.state(), floor_id=300, floor_reason="manual_trim_50"))
    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.until_live()

    submit(
        second,
        edit_event(298, "below"),
        edit_event(299, "below"),
        edit_event(300, "at floor"),
        edit_event(301, "above"),
        delete_event([298, 299]),
    )
    submit(second, delete_event([299, 300, 301]))
    await second.settle()
    await second.worker.stop()

    records = records_on_disk(second.folder)
    edits = sorted(r.msg_id for r in records if isinstance(r, EditRecord))
    deletes = [r.msg_ids for r in records if isinstance(r, DeleteRecord)]
    assert edits == [300, 301]
    assert deletes == [(300, 301)]


@pytest.mark.parametrize(("seconds", "reconciled"), [(599, False), (600, True), (601, True)])
async def test_reconcile_catches_up_what_the_events_missed(
    make_rig: RigFactory, seconds: float, reconciled: bool
) -> None:
    rig = await live_rig(make_rig, config=make_config(backfill={"pause_between_requests_sec": 0.0}))
    for i in range(401, 404):
        rig.gateway.chats[CHAT_ID][i] = msg(i)
    since_before = rig.gateway.count("iter_since")

    rig.clock.advance(seconds=seconds)
    rig.worker.resume()
    await rig.settle()

    assert (rig.gateway.count("iter_since") == since_before + 1) is reconciled
    assert (max(rig.ids()) == 403) is reconciled
    if reconciled:
        await rig.until_live()
        assert_disk_consistent(rig.folder, expect_ids=range(1, 404))


async def test_reconcile_flushes_the_buffer_before_catching_up(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)
    submit(rig, new_event(401))
    await rig.settle()

    rig.clock.advance(seconds=601)
    rig.worker.resume()
    await rig.until(lambda: 401 in rig.ids(), "buffer flushed by reconcile")


async def test_events_queued_before_start_are_applied_after_catch_up_without_duplicates(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 401))
    rig.gateway.chats[CHAT_ID][401] = msg(401)
    submit(rig, new_event(401), new_event(402), new_event(100))

    rig.start()
    await rig.until_complete()
    await rig.worker.stop()

    assert_disk_consistent(rig.folder, expect_ids=range(1, 403))


async def test_stop_flushes_the_buffer_and_is_idempotent(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)
    submit(rig, new_event(401), new_event(402), new_event(403))
    await rig.settle()
    assert max(rig.ids()) == 400

    await rig.worker.stop()
    await rig.worker.stop()

    assert rig.task is not None
    assert rig.task.done()
    assert rig.task.exception() is None
    assert_disk_consistent(rig.folder, expect_ids=range(1, 404))
    stray = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert stray == []


async def test_stop_before_run_makes_run_return_immediately(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 5))

    await rig.worker.stop()
    await asyncio.wait_for(rig.worker.run(), 1)

    assert rig.gateway.calls == []
    assert not rig.root.exists()


async def test_stop_cancels_a_run_that_does_not_finish_in_the_grace_period(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chatimport.worker._STOP_GRACE_SECONDS", 0.05)
    rig = make_rig(gateway=HangingGateway())
    task = rig.start()
    await rig.settle()

    await asyncio.wait_for(rig.worker.stop(), 2)

    assert task.done()


async def test_stop_while_backfill_is_paused_does_not_hang(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 1001))
    rig.worker.pause_backfill()
    rig.start()
    await rig.until_live()
    await rig.settle()

    await asyncio.wait_for(rig.worker.stop(), 2)

    assert rig.task is not None
    assert rig.task.done()


async def test_the_chat_lock_serialises_flushes_with_other_writers(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)

    async with rig.worker.lock:
        submit(rig, *(new_event(i) for i in range(401, 406)))
        await rig.settle()
        assert max(rig.ids()) == 400

    await rig.until(lambda: max(rig.ids()) == 405, "flush after the lock is released")
    assert_disk_consistent(rig.folder, expect_ids=range(1, 406))


async def test_pause_flushes_the_buffer_holds_new_events_and_resume_catches_up(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)
    submit(rig, new_event(401), new_event(402), new_event(403))

    rig.worker.pause()
    await rig.until(lambda: rig.phase() == PHASE_PAUSED, "parked")

    assert rig.ids()[-3:] == [401, 402, 403]
    status = rig.worker.status()
    assert (status.paused, status.phase) == (True, PHASE_PAUSED)

    submit(rig, new_event(404), new_event(405))
    rig.clock.advance(seconds=3600)
    await rig.settle()
    assert max(rig.ids()) == 403
    assert rig.phase() == PHASE_PAUSED

    for i in (404, 405, 406):
        rig.gateway.chats[CHAT_ID][i] = msg(i)
    rig.worker.resume()
    await rig.until(lambda: 406 in rig.ids(), "catch-up after resume")
    await rig.until_live()
    assert not rig.worker.status().paused

    await rig.worker.stop()
    assert_disk_consistent(rig.folder, expect_ids=[*range(1, 407)])


async def test_stop_while_paused_returns_and_flushes(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)
    rig.worker.pause()
    await rig.until(lambda: rig.phase() == PHASE_PAUSED, "parked")
    submit(rig, new_event(401))

    await asyncio.wait_for(rig.worker.stop(), 2)

    assert rig.task is not None
    assert rig.task.done()


async def test_pause_before_start_keeps_the_head_backfill_from_reading_history(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 51))
    rig.worker.pause()
    rig.start()
    await rig.until(lambda: rig.phase() == PHASE_PAUSED, "parked in head backfill")
    await rig.settle()

    assert rig.gateway.count("iter_history") == 0
    assert list_parts(rig.folder) == []

    rig.worker.resume()
    await rig.until_complete()
    assert_disk_consistent(rig.folder, expect_ids=range(1, 51))


async def test_backfill_pause_stops_only_the_history_download(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 1001))
    rig.worker.pause_backfill()
    rig.start()
    await rig.until_live()
    await rig.settle()

    assert rig.ids() == list(range(316, 1001))
    assert not rig.state().backfill.done

    submit(rig, *(new_event(i) for i in range(1001, 1006)))
    await rig.until(lambda: max(rig.ids()) == 1005, "live flush while the backfill is paused")
    assert min(rig.ids()) == 316

    rig.worker.resume_backfill()
    await rig.until_complete()
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1006))


async def test_resuming_the_worker_does_not_release_a_paused_backfill(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    rig.worker.pause_backfill()
    rig.worker.pause()
    rig.start()
    await rig.until(lambda: rig.phase() == PHASE_PAUSED, "parked")

    rig.worker.resume()
    await rig.until_live()
    await rig.settle()
    assert not rig.state().backfill.done

    rig.worker.resume_backfill()
    await rig.until_complete()


@pytest.mark.parametrize("backfill_paused", [False, True])
async def test_refetch_after_the_folder_was_deleted_downloads_everything_again(
    make_rig: RigFactory, backfill_paused: bool
) -> None:
    rig = make_rig(range(1, 1001))
    if backfill_paused:
        rig.worker.pause_backfill()
    rig.start()
    await rig.until_live()
    if not backfill_paused:
        await rig.until_complete()

    shutil.rmtree(rig.folder)
    rig.worker.resume_backfill()
    rig.worker.request_refetch()
    await rig.until_complete()

    state = rig.state()
    assert (state.floor_id, state.floor_reason, state.last_id) == (0, None, 1000)
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


@pytest.mark.parametrize("damage", ["deleted", "garbage", "truncated", "empty"])
async def test_a_broken_state_file_while_live_heals_at_the_next_reconcile(
    make_rig: RigFactory, damage: str
) -> None:
    rig = await live_rig(make_rig)
    for i in range(401, 406):
        rig.gateway.chats[CHAT_ID][i] = msg(i)
    state_file = rig.folder / "state.json"
    original = state_file.read_text(encoding="utf-8")
    if damage == "deleted":
        state_file.unlink()
    else:
        state_file.write_text(
            {"garbage": "{not json", "truncated": original[: len(original) // 2], "empty": ""}[
                damage
            ],
            encoding="utf-8",
        )

    submit(rig, *(new_event(i) for i in range(401, 406)))
    await rig.settle()
    assert rig.ids() == list(range(1, 401))

    rig.clock.advance(seconds=601)
    rig.worker.resume()
    await rig.until(lambda: rig.is_live() and max(rig.ids()) == 405, "healed")

    assert 20 in rig.clock.sleeps
    assert_disk_consistent(rig.folder, expect_ids=range(1, 406))


async def test_a_folder_deleted_while_live_is_refetched_at_the_next_reconcile(
    make_rig: RigFactory,
) -> None:
    rig = await live_rig(make_rig)
    shutil.rmtree(rig.folder)
    submit(rig, *(new_event(i) for i in range(401, 406)))
    await rig.settle()
    for i in range(401, 406):
        rig.gateway.chats[CHAT_ID][i] = msg(i)

    rig.clock.advance(seconds=601)
    rig.worker.resume()
    await rig.until(
        lambda: rig.is_live() and rig.backfill_done() and rig.ids() == list(range(1, 406)),
        "refetched",
    )
    assert_disk_consistent(rig.folder, expect_ids=range(1, 406))


async def test_folder_deleted_in_the_middle_of_the_tail_backfill_triggers_a_full_refetch(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    seen = 0

    def hook() -> None:
        nonlocal seen
        if any(name == "iter_history" and args[1] for name, args in rig.gateway.calls):
            seen += 1
            if seen == 20:
                shutil.rmtree(rig.folder)

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until(
        lambda: seen >= 20 and rig.is_live() and rig.backfill_done() and len(rig.ids()) == 1000,
        "refetched after the deletion",
    )
    assert 20 in rig.clock.sleeps
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_failed_state_save_after_the_data_write_never_duplicates_messages(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await live_rig(make_rig)
    failures = [PermissionError("state.json is locked")]

    def flaky(folder: Path, state: Any) -> None:
        if failures:
            raise failures.pop()
        save_state(folder, state)

    monkeypatch.setattr("chatimport.storage.writer.save_state", flaky)

    submit(rig, *(new_event(i) for i in range(401, 406)))
    assert rig.task is not None
    with pytest.raises(PermissionError):
        await asyncio.wait_for(rig.task, 3)

    assert_disk_consistent(rig.folder)


async def test_a_state_save_failure_in_catch_up_is_repaired_by_the_next_worker(
    make_rig: RigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await live_rig(make_rig, range(1, 11))
    await first.shutdown()
    for i in range(11, 31):
        first.gateway.chats[CHAT_ID][i] = msg(i)
    failures = [OSError("disk full")]

    def flaky(folder: Path, state: Any) -> None:
        if failures:
            raise failures.pop()
        save_state(folder, state)

    monkeypatch.setattr("chatimport.storage.writer.save_state", flaky)
    crashed = make_rig(gateway=first.gateway, clock=first.clock)
    task = crashed.start()
    with pytest.raises(OSError, match="disk full"):
        await asyncio.wait_for(task, 3)

    resumed = make_rig(gateway=first.gateway, clock=first.clock)
    resumed.start()
    await resumed.until(lambda: resumed.is_live() and resumed.ids() == list(range(1, 31)), "ok")
    assert_disk_consistent(resumed.folder, expect_ids=range(1, 31))


async def test_a_generic_failure_propagates_and_run_can_be_started_again(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 51))
    rig.gateway.fail["newest_id"] = [RuntimeError("boom")]

    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(rig.worker.run(), 2)
    assert rig.worker.status().error == "RuntimeError"

    rig.start()
    await rig.until_complete()
    assert rig.worker.status().error is None
    assert_disk_consistent(rig.folder, expect_ids=range(1, 51))


async def test_status_before_the_first_run_reports_a_blank_chat(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 5))

    status = rig.worker.status()

    assert (status.chat_id, status.title, status.phase) == (CHAT_ID, "Example Chat", PHASE_RECOVER)
    assert (status.last_id, status.backfill_done, status.records, status.paused) == (
        0,
        False,
        0,
        False,
    )
    assert (status.oldest_date, status.error) == (None, None)


async def test_status_of_a_live_chat_reflects_the_files(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig, range(1, 1001))

    status = rig.worker.status()

    assert (status.phase, status.last_id, status.backfill_done) == (PHASE_LIVE, 1000, True)
    assert status.records == 1000
    assert status.oldest_date == msg(1).date
    assert status.error is None


async def test_status_of_a_fresh_worker_over_an_existing_folder_reads_state_json(
    make_rig: RigFactory,
) -> None:
    first = await live_rig(make_rig, range(1, 21))
    await first.shutdown()

    second = make_rig(gateway=first.gateway, clock=first.clock)
    status = second.worker.status()

    assert (status.last_id, status.records, status.backfill_done) == (20, 20, True)
    assert status.oldest_date is None


async def test_the_folder_property_follows_a_renamed_folder(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig, range(1, 11))
    old = rig.folder
    renamed = old.with_name("renamed_by_the_user")
    old.rename(renamed)

    assert rig.worker.folder == renamed
    submit(rig, *(new_event(i) for i in range(11, 16)))
    await rig.until(lambda: max(rig.ids()) == 15, "flush into the renamed folder")
    assert_disk_consistent(renamed, expect_ids=range(1, 16))


async def test_events_still_queued_when_stop_arrives_are_flushed(make_rig: RigFactory) -> None:
    rig = await live_rig(make_rig)

    async with rig.worker.lock:
        submit(rig, *(new_event(i) for i in range(401, 406)))
        await rig.settle()
        submit(rig, new_event(406), new_event(407))
        stopping = asyncio.create_task(rig.worker.stop())
        await rig.settle()
    await asyncio.wait_for(stopping, 3)

    assert_disk_consistent(rig.folder, expect_ids=range(1, 408))
