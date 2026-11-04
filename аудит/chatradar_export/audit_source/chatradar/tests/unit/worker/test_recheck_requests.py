"""How the worker schedules, runs and records a recheck (the comparison itself is tested in
test_recheck_compute.py)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.ports import FloodWait
from chatimport.records import (
    DETECTED_RECHECK,
    DeleteRecord,
    EditRecord,
    MessageRecord,
    Record,
)
from chatimport.storage.state import PHASE_LIVE, PHASE_PAUSED, save_state
from chatimport.storage.writer import iter_records
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.worker.rig import (
    Rig,
    RigFactory,
    assert_disk_consistent,
    make_config,
    make_rig,
    new_event,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from chatimport.ports import TelegramGateway
    from chatimport.storage.state import ChatState

__all__ = ["make_rig"]


class FakeRecheck:
    def __init__(self, result: list[Record] | None = None) -> None:
        self.result = result or []
        self.failures: list[BaseException] = []
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        gateway: TelegramGateway,
        folder: Path,
        state: ChatState,
        *,
        now: datetime,
        days: int,
        track_edits: bool,
        track_deletes: bool,
    ) -> list[Record]:
        stored = [r.msg_id for r in iter_records(folder) if isinstance(r, MessageRecord)]
        self.calls.append(
            {
                "phase": state.phase,
                "now": now,
                "days": days,
                "edits": track_edits,
                "deletes": track_deletes,
                "stored": stored,
            }
        )
        if self.failures:
            raise self.failures.pop(0)
        return list(self.result)


async def live(make_rig: RigFactory, recheck: FakeRecheck, **kwargs: Any) -> Rig:
    rig = make_rig(kwargs.pop("ids", range(1, 401)), recheck=recheck, **kwargs)
    rig.start()
    await rig.until_complete()
    return rig


async def test_a_recheck_requested_before_start_waits_for_the_live_phase(
    make_rig: RigFactory,
) -> None:
    recheck = FakeRecheck()
    rig = make_rig(range(1, 401), recheck=recheck)
    rig.worker.request_recheck(3)

    rig.start()
    await rig.until(lambda: bool(recheck.calls), "recheck called")
    await rig.settle()

    assert len(recheck.calls) == 1
    call = recheck.calls[0]
    assert (call["phase"], call["days"]) == (PHASE_LIVE, 3)
    assert call["stored"][-1] == 400
    assert rig.gateway.count("iter_since") >= 1


async def test_a_recheck_waits_while_the_history_backfill_is_still_running(
    make_rig: RigFactory,
) -> None:
    recheck = FakeRecheck()
    rig = make_rig(range(1, 1001), recheck=recheck)
    rig.worker.pause_backfill()
    rig.start()
    await rig.until_live()

    rig.worker.request_recheck()
    await rig.settle()
    assert recheck.calls == []

    rig.worker.resume_backfill()
    await rig.until_complete()
    await rig.until(lambda: bool(recheck.calls), "recheck after the backfill")
    assert rig.state().backfill.done


async def test_a_recheck_without_days_uses_the_configured_window(make_rig: RigFactory) -> None:
    recheck = FakeRecheck()
    rig = await live(make_rig, recheck, config=make_config(recheck={"days": 5}))

    rig.worker.request_recheck()
    await rig.until(lambda: bool(recheck.calls), "recheck called")

    assert recheck.calls[0]["days"] == 5


async def test_a_recheck_passes_the_tracking_switches_and_the_clock(
    make_rig: RigFactory,
) -> None:
    recheck = FakeRecheck()
    config = make_config(events={"track_edits": False, "track_deletes": True})
    rig = await live(make_rig, recheck, config=config)

    rig.worker.request_recheck(2)
    await rig.until(lambda: bool(recheck.calls), "recheck called")

    call = recheck.calls[0]
    assert (call["edits"], call["deletes"]) == (False, True)
    assert call["now"] == rig.clock.now()


async def test_the_last_of_several_requests_wins_and_runs_once(make_rig: RigFactory) -> None:
    recheck = FakeRecheck()
    rig = make_rig(range(1, 51), recheck=recheck)
    rig.worker.request_recheck(2)
    rig.worker.request_recheck(9)

    rig.start()
    await rig.until(lambda: bool(recheck.calls), "recheck called")
    await rig.settle()

    assert [c["days"] for c in recheck.calls] == [9]


async def test_the_recheck_result_is_appended_and_last_recheck_at_is_set(
    make_rig: RigFactory,
) -> None:
    edit_date = NOW + timedelta(hours=1)
    recheck = FakeRecheck(
        [
            EditRecord(CHAT_ID, 10, edit_date, NOW, "after", None, DETECTED_RECHECK),
            msg(200),
            DeleteRecord(CHAT_ID, (20,), NOW, DETECTED_RECHECK),
        ]
    )
    rig = await live(make_rig, recheck, ids=[i for i in range(1, 401) if i != 200])

    rig.worker.request_recheck(60)
    await rig.until(lambda: rig.state().last_recheck_at is not None, "recheck recorded")

    state = rig.state()
    assert state.last_recheck_at == rig.clock.now()
    assert state.last_id == 400
    records = list(iter_records(rig.folder))
    assert 200 in [r.msg_id for r in records if isinstance(r, MessageRecord)]
    assert [r.detected_by for r in records if isinstance(r, EditRecord | DeleteRecord)] == [
        DETECTED_RECHECK,
        DETECTED_RECHECK,
    ]
    assert_disk_consistent(rig.folder, ordered=False)


async def test_an_empty_recheck_result_still_stamps_the_time_and_changes_no_data(
    make_rig: RigFactory,
) -> None:
    recheck = FakeRecheck()
    rig = await live(make_rig, recheck)
    before = {p.name: p.read_bytes() for p in rig.folder.glob("*.jsonl")}
    rig.clock.advance(hours=5)

    rig.worker.request_recheck()
    await rig.until(lambda: rig.state().last_recheck_at is not None, "stamped")

    assert rig.state().last_recheck_at == rig.clock.now()
    assert {p.name: p.read_bytes() for p in rig.folder.glob("*.jsonl")} == before


async def test_recheck_results_at_or_below_the_floor_are_not_written(
    make_rig: RigFactory,
) -> None:
    first = await live(
        make_rig, FakeRecheck(), ids=[i for i in range(1, 401) if i not in (250, 305)]
    )
    await first.shutdown()
    save_state(first.folder, replace(first.state(), floor_id=300))
    recheck = FakeRecheck([msg(250), msg(300), msg(305)])
    second = make_rig(gateway=first.gateway, clock=first.clock, recheck=recheck)
    second.start()
    await second.until_live()

    second.worker.request_recheck()
    await second.until(lambda: second.state().last_recheck_at is not None, "recheck recorded")

    ids = [i for i in second.ids() if i in (250, 300, 305)]
    assert sorted(ids) == [300, 305]


async def test_a_recheck_flushes_buffered_events_first(make_rig: RigFactory) -> None:
    recheck = FakeRecheck()
    rig = await live(make_rig, recheck)
    for i in (401, 402):
        rig.worker.submit(new_event(i))
    await rig.settle()

    rig.worker.request_recheck()
    await rig.until(lambda: bool(recheck.calls), "recheck called")

    assert recheck.calls[0]["stored"][-2:] == [401, 402]


async def test_a_flood_wait_in_the_recheck_is_waited_out_and_retried(make_rig: RigFactory) -> None:
    recheck = FakeRecheck()
    recheck.failures = [FloodWait(7)]
    rig = await live(make_rig, recheck)

    rig.worker.request_recheck()
    await rig.until(lambda: rig.state().last_recheck_at is not None, "recheck recorded")

    assert len(recheck.calls) == 2
    assert 7 in rig.clock.sleeps


async def test_a_failing_recheck_ends_the_run_with_the_error_class_only(
    make_rig: RigFactory,
) -> None:
    recheck = FakeRecheck()
    recheck.failures = [RuntimeError("secret detail")]
    rig = await live(make_rig, recheck)

    rig.worker.request_recheck()
    assert rig.task is not None
    with pytest.raises(RuntimeError, match="secret detail"):
        await asyncio.wait_for(rig.task, 3)

    assert rig.worker.status().error == "RuntimeError"
    assert rig.state().last_recheck_at is None


async def test_a_paused_worker_postpones_the_recheck_until_it_resumes(
    make_rig: RigFactory,
) -> None:
    recheck = FakeRecheck()
    rig = await live(make_rig, recheck)
    rig.worker.pause()
    await rig.until(lambda: rig.phase() == PHASE_PAUSED, "parked")

    rig.worker.request_recheck()
    await rig.settle()
    assert recheck.calls == []

    rig.worker.resume()
    await rig.until(lambda: bool(recheck.calls), "recheck after resume")
    assert recheck.calls[0]["phase"] == PHASE_LIVE
