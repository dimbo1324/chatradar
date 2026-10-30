"""Head backfill, tail backfill and catch-up of the chat worker, checked against the disk."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.ports import FloodWait
from chatimport.records import MessageRecord
from chatimport.storage.layout import list_parts, month_key, parse_part_name
from chatimport.storage.state import PHASE_HEAD_BACKFILL
from chatimport.storage.writer import iter_part_records
from tests.fakes import CHAT_ID, NOW, FakeGateway, msg
from tests.unit.worker.rig import (
    RigFactory,
    assert_disk_consistent,
    make_config,
    make_rig,
    small_parts,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["make_rig", "small_parts"]

OCTOBER_FIRST_ID = 316  # msg(316) is dated exactly 2026-10-01T00:00:00Z


def at(msg_id: int, iso: str, **kwargs: Any) -> MessageRecord:
    return msg(msg_id, date=datetime.fromisoformat(iso), **kwargs)


def put(gateway: FakeGateway, records: list[MessageRecord], chat_id: int = CHAT_ID) -> None:
    gateway.chats.setdefault(chat_id, {}).update({r.msg_id: r for r in records})


def tail_calls(gateway: FakeGateway) -> list[tuple[Any, ...]]:
    return [args for name, args in gateway.calls if name == "iter_history" and args[1]]


def ids_by_part(folder: Path) -> dict[str, list[int]]:
    return {
        p.stem: [r.msg_id for r in iter_part_records(p) if isinstance(r, MessageRecord)]
        for p in list_parts(folder)
    }


def test_fixture_dates_put_message_316_exactly_at_midnight() -> None:
    assert msg(OCTOBER_FIRST_ID).date == datetime(2026, 10, 1, tzinfo=UTC)
    assert msg(OCTOBER_FIRST_ID - 1).date == datetime(2026, 9, 30, 23, tzinfo=UTC)


async def test_empty_chat_finishes_without_reading_history(make_rig: RigFactory) -> None:
    rig = make_rig()
    rig.start()

    await rig.until_complete()

    state = rig.state()
    assert (state.last_id, state.chunks) == (0, {})
    assert state.backfill.head_id == 0
    assert rig.gateway.count("iter_history") == 0
    assert rig.ids() == []
    assert_disk_consistent(rig.folder)


async def test_restart_of_an_empty_chat_does_not_repeat_the_head_backfill(
    make_rig: RigFactory,
) -> None:
    first = make_rig()
    first.start()
    await first.until_complete()
    await first.shutdown()

    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.gateway.chats[CHAT_ID] = {5: msg(5)}
    second.start()
    await second.until(lambda: second.ids() == [5], "message 5 caught up")

    assert second.gateway.count("newest_id") == 1
    assert second.gateway.count("iter_history") == 0
    assert second.state().last_id == 5
    assert_disk_consistent(second.folder, expect_ids=[5])


async def test_single_message_chat_is_stored_and_backfill_completes(make_rig: RigFactory) -> None:
    rig = make_rig([7])
    rig.start()

    await rig.until_complete()

    state = rig.state()
    assert (state.last_id, state.backfill.head_id, state.backfill.oldest_done_id) == (7, 7, 7)
    assert_disk_consistent(rig.folder, expect_ids=[7])
    assert len(list_parts(rig.folder)) == 1


async def test_chat_with_only_old_messages_never_creates_a_current_month_file(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 200))
    rig.start()

    await rig.until_complete()

    assert list(ids_by_part(rig.folder)) == ["2026-09_001"]
    assert_disk_consistent(rig.folder, expect_ids=range(1, 200))


async def test_newest_message_from_a_sparse_old_month_pulls_in_the_gaps_below(
    make_rig: RigFactory,
) -> None:
    rig = make_rig()
    put(
        rig.gateway,
        [
            at(1, "2025-01-15T10:00:00+00:00"),
            at(2, "2025-06-30T10:00:00+00:00"),
            at(3, "2026-08-01T00:00:00+00:00"),
            at(4, "2026-08-31T23:59:59+00:00"),
        ],
    )
    rig.start()

    await rig.until_complete()

    assert ids_by_part(rig.folder) == {
        "2025-01_001": [1],
        "2025-06_001": [2],
        "2026-08_001": [3, 4],
    }
    assert_disk_consistent(rig.folder, expect_ids=[1, 2, 3, 4])


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        pytest.param(
            [
                (1, "2026-09-30T23:59:59+00:00"),
                (2, "2026-10-01T00:00:00+00:00"),
                (3, "2026-10-01T00:00:01+00:00"),
            ],
            {"2026-09_001": [1], "2026-10_001": [2, 3]},
            id="utc-midnight",
        ),
        pytest.param(
            [(1, "2026-10-01T02:59:59+03:00"), (2, "2026-10-01T03:00:00+03:00")],
            {"2026-09_001": [1], "2026-10_001": [2]},
            id="positive-offset",
        ),
        pytest.param(
            [(1, "2026-09-30T18:59:59-05:00"), (2, "2026-09-30T19:00:00-05:00")],
            {"2026-09_001": [1], "2026-10_001": [2]},
            id="negative-offset",
        ),
        pytest.param(
            [(1, "2025-12-31T23:59:59+00:00"), (2, "2026-01-01T00:00:00+00:00")],
            {"2025-12_001": [1], "2026-01_001": [2]},
            id="year-boundary",
        ),
        pytest.param(
            [(1, "2028-02-29T23:59:59+00:00"), (2, "2028-03-01T00:00:00+00:00")],
            {"2028-02_001": [1], "2028-03_001": [2]},
            id="leap-day",
        ),
        pytest.param(
            [(1, "2026-10-31T23:59:59.999999+00:00"), (2, "2026-11-01T00:00:00+00:00")],
            {"2026-10_001": [1], "2026-11_001": [2]},
            id="microseconds-before-midnight",
        ),
    ],
)
async def test_month_boundaries_follow_utc_midnight(
    make_rig: RigFactory, records: list[tuple[int, str]], expected: dict[str, list[int]]
) -> None:
    rig = make_rig()
    put(rig.gateway, [at(i, iso) for i, iso in records])
    rig.start()

    await rig.until_complete()

    assert ids_by_part(rig.folder) == expected
    assert_disk_consistent(rig.folder)


async def test_head_backfill_puts_the_current_month_on_disk_before_older_history(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    snapshots: list[list[int]] = []

    def hook() -> None:
        if tail_calls(rig.gateway) and not snapshots:
            snapshots.append(rig.ids())

    rig.gateway.page_hook = hook
    rig.start()
    await rig.until_complete()

    assert snapshots == [list(range(OCTOBER_FIRST_ID, 1001))]
    assert tail_calls(rig.gateway)[0][1:] == (OCTOBER_FIRST_ID, 0)
    state = rig.state()
    assert state.backfill.oldest_done_id == 1
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_head_backfill_with_a_deleted_head_message_still_completes(
    make_rig: RigFactory,
) -> None:
    class GhostHead(FakeGateway):
        async def newest_id(self, chat_id: int) -> int:
            return 99

    gateway = GhostHead()
    rig = make_rig(gateway=gateway)
    rig.start()
    await rig.until_complete()

    state = rig.state()
    assert (state.last_id, state.backfill.head_id, list_parts(rig.folder)) == (99, 99, [])

    await rig.shutdown()
    gateway.chats[CHAT_ID] = {100: msg(100)}
    again = make_rig(gateway=gateway, clock=rig.clock)
    again.start()
    await again.until(lambda: again.ids() == [100], "message 100 caught up")


async def test_head_backfill_pauses_between_batches(make_rig: RigFactory) -> None:
    config = make_config(backfill={"batch_size": 3, "pause_between_requests_sec": 2.5})
    rig = make_rig(range(1, 11), config=config)
    rig.start()

    await rig.until_complete()

    assert rig.clock.sleeps == [2.5, 2.5, 2.5]


async def test_stop_during_head_backfill_leaves_no_partial_data_and_restart_completes(
    make_rig: RigFactory,
) -> None:
    config = make_config(backfill={"batch_size": 3})
    rig = make_rig(range(1, 11), config=config)
    stops: list[asyncio.Task[None]] = []
    seen = 0

    def hook() -> None:
        nonlocal seen
        seen += 1
        if seen == 5:
            stops.append(asyncio.get_running_loop().create_task(rig.worker.stop()))

    rig.gateway.page_hook = hook
    task = rig.start()
    await asyncio.wait_for(task, 3)
    await asyncio.gather(*stops)

    assert list_parts(rig.folder) == []
    state = rig.state()
    assert (state.phase, state.backfill.done, state.chunks) == (PHASE_HEAD_BACKFILL, False, {})

    rig.gateway.page_hook = None
    second = make_rig(gateway=rig.gateway, clock=rig.clock, config=config)
    second.start()
    await second.until_complete()
    assert_disk_consistent(second.folder, expect_ids=range(1, 11))


async def test_full_tail_backfill_reaches_the_start_of_history(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 1001))
    rig.start()

    await rig.until_complete()

    state = rig.state()
    assert state.backfill.done
    assert (state.backfill.head_id, state.backfill.oldest_done_id, state.last_id) == (1000, 1, 1000)
    assert (state.floor_id, state.floor_reason) == (0, None)
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))
    assert rig.gateway.count("iter_history") == 2


async def test_thousands_of_messages_over_many_months_in_tiny_parts(
    make_rig: RigFactory, small_parts: int
) -> None:
    start = datetime(2024, 11, 1, tzinfo=UTC)
    rig = make_rig(config=make_config(backfill={"batch_size": 50}))
    total = 2400
    put(
        rig.gateway,
        [
            msg(i, date=start + timedelta(hours=8 * i), text=f"{'x' * 100} {i}")
            for i in range(1, total + 1)
        ],
    )
    rig.start()

    await rig.until_complete()

    assert_disk_consistent(rig.folder, expect_ids=range(1, total + 1))
    by_month: dict[str, list[int]] = {}
    for part in list_parts(rig.folder):
        parsed = parse_part_name(part.name)
        assert parsed is not None
        by_month.setdefault(parsed[0], []).append(parsed[1])
        for record in iter_part_records(part):
            assert month_key(record.date if isinstance(record, MessageRecord) else NOW) == parsed[0]
    assert len(by_month) >= 26
    for month, numbers in by_month.items():
        assert numbers == list(range(1, len(numbers) + 1)), month
        for number in numbers[:-1]:
            path = rig.folder / f"{month}_{number:03d}.jsonl"
            assert path.stat().st_size >= small_parts
    assert rig.clock.sleeps.count(1.0) >= total // 50 - 2


@pytest.mark.parametrize("mode", ["cancel", "crash"])
@pytest.mark.parametrize("cut", [1, 7, 150, 299, 315])
async def test_interrupted_tail_resumes_from_oldest_done_id_without_gaps_or_duplicates(
    make_rig: RigFactory, cut: int, mode: str
) -> None:
    first = make_rig(range(1, 1001))
    seen = 0

    def hook() -> None:
        nonlocal seen
        if not tail_calls(first.gateway):
            return
        seen += 1
        if seen == cut:
            if mode == "crash":
                raise RuntimeError("simulated crash")
            assert first.task is not None
            first.task.cancel()
            raise asyncio.CancelledError

    first.gateway.page_hook = hook
    task = first.start()
    if mode == "crash":
        with pytest.raises(RuntimeError, match="simulated crash"):
            await asyncio.wait_for(task, 5)
    else:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)

    interrupted = first.state()
    assert not interrupted.backfill.done
    stored = set(assert_disk_consistent(first.folder))
    assert set(range(interrupted.backfill.oldest_done_id, 1001)) <= stored

    first.gateway.page_hook = None
    mark = len(first.gateway.calls)
    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.until_complete()

    resumed = [args for name, args in second.gateway.calls[mark:] if name == "iter_history"]
    assert resumed[0][1] == interrupted.backfill.oldest_done_id
    assert_disk_consistent(second.folder, expect_ids=range(1, 1001))


async def test_rolled_back_state_json_after_a_finished_backfill_rewrites_nothing(
    make_rig: RigFactory,
) -> None:
    first = make_rig(range(1, 1001))
    snapshot: list[str] = []

    def hook() -> None:
        if tail_calls(first.gateway) and not snapshot:
            snapshot.append((first.folder / "state.json").read_text(encoding="utf-8"))

    first.gateway.page_hook = hook
    first.start()
    await first.until_complete()
    await first.shutdown()
    before = {p.name: p.read_bytes() for p in list_parts(first.folder)}

    (first.folder / "state.json").write_text(snapshot[0], encoding="utf-8")
    first.gateway.page_hook = None
    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.until_complete()

    assert {p.name: p.read_bytes() for p in list_parts(second.folder)} == before
    assert_disk_consistent(second.folder, expect_ids=range(1, 1001))


async def test_catch_up_after_offline_growth_crosses_a_month_boundary(
    make_rig: RigFactory,
) -> None:
    first = make_rig(range(1, 401))
    first.start()
    await first.until_complete()
    await first.shutdown()

    for i in range(401, 651):
        first.gateway.chats[CHAT_ID][i] = msg(i)
    put(
        first.gateway,
        [
            at(651, "2026-10-31T23:59:59+00:00"),
            at(652, "2026-11-01T00:00:00+00:00"),
            at(653, "2026-11-02T00:00:00+00:00"),
        ],
    )
    mark = len(first.gateway.calls)
    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.until(lambda: second.is_live() and 653 in second.ids(), "caught up")

    assert second.gateway.calls[mark:].count(("iter_since", (CHAT_ID, 400))) == 1
    assert ids_by_part(second.folder)["2026-11_001"] == [652, 653]
    assert 651 in ids_by_part(second.folder)["2026-10_001"]
    assert second.state().last_id == 653
    assert_disk_consistent(second.folder, expect_ids=range(1, 654))


async def test_catch_up_retries_after_a_flood_wait_without_duplicates(
    make_rig: RigFactory,
) -> None:
    first = make_rig(range(1, 11))
    first.start()
    await first.until_complete()
    await first.shutdown()
    for i in range(11, 18):
        first.gateway.chats[CHAT_ID][i] = msg(i)
    calls = 0

    def hook() -> None:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise FloodWait(4)

    first.gateway.page_hook = hook
    mark = len(first.gateway.calls)
    second = make_rig(
        gateway=first.gateway, clock=first.clock, config=make_config(backfill={"batch_size": 2})
    )
    second.start()
    await second.until(lambda: second.is_live() and 17 in second.ids(), "caught up")

    assert 4 in second.clock.sleeps
    since_calls = [a for n, a in second.gateway.calls[mark:] if n == "iter_since"]
    assert since_calls == [(CHAT_ID, 10), (CHAT_ID, 14)]
    assert_disk_consistent(second.folder, expect_ids=range(1, 18))


async def test_pause_during_catch_up_is_honoured_at_the_next_batch_boundary(
    make_rig: RigFactory,
) -> None:
    first = make_rig(range(1, 11))
    first.start()
    await first.until_complete()
    await first.shutdown()
    for i in range(11, 18):
        first.gateway.chats[CHAT_ID][i] = msg(i)
    config = make_config(backfill={"batch_size": 2})
    second = make_rig(gateway=first.gateway, clock=first.clock, config=config)
    calls = 0

    def hook() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            second.worker.pause()

    first.gateway.page_hook = hook
    second.start()
    await second.until(lambda: second.phase() == "paused", "parked")

    assert second.state().last_id == 14
    assert max(second.ids()) == 14
    assert second.worker.status().paused

    second.worker.resume()
    await second.until(lambda: second.is_live() and 17 in second.ids(), "caught up after resume")
    assert_disk_consistent(second.folder, expect_ids=range(1, 18))
