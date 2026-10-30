"""FloodWait, lost access and revoked sessions in every phase of the chat worker."""

from __future__ import annotations

import asyncio

import pytest

from chatimport.ports import AccessLost, FloodWait, SessionRevoked
from chatimport.runtime import Level
from chatimport.storage.state import PHASE_NO_ACCESS
from tests.fakes import CHAT_ID, FakeClock, msg
from tests.unit.worker.rig import (
    TITLE,
    Rig,
    RigFactory,
    assert_disk_consistent,
    make_rig,
    new_event,
)

__all__ = ["make_rig"]


class GatedClock(FakeClock):
    """A clock whose sleeps of exactly `blocked` seconds wait until `gate` is set."""

    def __init__(self, blocked: float) -> None:
        super().__init__()
        self.blocked = blocked
        self.gate = asyncio.Event()
        self.gated: list[float] = []

    async def sleep(self, seconds: float) -> None:
        if seconds == self.blocked:
            self.gated.append(seconds)
            await self.gate.wait()
            return
        await super().sleep(seconds)


def tail_started(rig: Rig) -> bool:
    return any(name == "iter_history" and args[1] for name, args in rig.gateway.calls)


def fail_once_in_tail(rig: Rig, error: BaseException, after: int = 1) -> None:
    seen = 0
    fired = False

    def hook() -> None:
        nonlocal seen, fired
        if tail_started(rig) and not fired:
            seen += 1
            if seen == after:
                fired = True
                raise error

    rig.gateway.page_hook = hook


async def prepare_site(make_rig: RigFactory, site: str, error: BaseException) -> Rig:
    """A rig that will hit `error` once at `site`; the matching history is on the gateway."""
    if site == "catch_up":
        first = make_rig(range(1, 51))
        first.start()
        await first.until_complete()
        await first.shutdown()
        for i in range(51, 61):
            first.gateway.chats[CHAT_ID][i] = msg(i)
        first.gateway.fail["iter_since"] = [error]
        return make_rig(gateway=first.gateway, clock=first.clock)
    rig = make_rig(range(1, 1001) if site == "tail" else range(1, 51))
    if site == "head_newest":
        rig.gateway.fail["newest_id"] = [error]
    elif site == "head_history":
        rig.gateway.fail["iter_history"] = [error]
    else:
        fail_once_in_tail(rig, error, after=3)
    return rig


SITES = ["head_newest", "head_history", "tail", "catch_up"]


def expected_ids(site: str) -> range:
    return {"tail": range(1, 1001), "catch_up": range(1, 61)}.get(site, range(1, 51))


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize(
    ("seconds", "notified"), [(1, False), (600, False), (601, True), (86400, True)]
)
async def test_flood_wait_sleeps_through_the_clock_and_notifies_only_above_ten_minutes(
    make_rig: RigFactory, site: str, seconds: int, notified: bool
) -> None:
    rig = await prepare_site(make_rig, site, FloodWait(seconds))
    mark = len(rig.clock.sleeps)
    rig.start()

    await rig.until(
        lambda: rig.is_live() and rig.backfill_done() and set(rig.ids()) == set(expected_ids(site)),
        "stored after the flood wait",
    )

    assert seconds in rig.clock.sleeps[mark:]
    warnings = [n for n in rig.notifier.notes if n.level is Level.WARNING]
    assert len(warnings) == int(notified)
    if notified:
        assert warnings[0].title == TITLE
        assert str(seconds) in warnings[0].message
    assert not [n for n in rig.notifier.notes if n.level is Level.ERROR]
    assert rig.worker.status().error is None
    assert_disk_consistent(rig.folder, expect_ids=expected_ids(site))


async def test_consecutive_flood_waits_are_all_served_in_order(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 51))
    rig.gateway.fail["newest_id"] = [FloodWait(1), FloodWait(2), FloodWait(3)]
    rig.start()

    await rig.until_complete()

    assert rig.clock.sleeps == [1, 2, 3]
    assert rig.gateway.count("newest_id") == 4


async def test_a_flood_wait_in_the_middle_of_a_stream_resumes_without_gaps(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    fail_once_in_tail(rig, FloodWait(9), after=40)
    rig.start()

    await rig.until_complete()

    assert 9 in rig.clock.sleeps
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_a_flood_wait_in_one_worker_does_not_block_another(make_rig: RigFactory) -> None:
    clock = GatedClock(1000)
    slow = make_rig(range(1, 51), title="Slow", clock=clock)
    fast = make_rig(range(1, 51), chat_id=CHAT_ID - 1, title="Fast", clock=clock)
    slow.gateway.fail["newest_id"] = [FloodWait(1000)]

    slow.start()
    fast.start()
    await fast.until_complete()

    assert clock.gated == [1000]
    assert not slow.is_live()
    clock.gate.set()
    await slow.until_complete()
    assert_disk_consistent(slow.folder, expect_ids=range(1, 51))


async def test_lost_access_during_the_head_backfill_keeps_state_and_drops_events(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 51))
    rig.gateway.fail["newest_id"] = [AccessLost(CHAT_ID)]
    task = rig.start()
    await rig.until(lambda: rig.phase() == PHASE_NO_ACCESS, "no access")

    for i in range(51, 71):
        rig.worker.submit(new_event(i))
    rig.worker.resume()
    await rig.settle()

    status = rig.worker.status()
    assert (status.phase, status.error) == (PHASE_NO_ACCESS, "no access")
    errors = [n for n in rig.notifier.notes if n.level is Level.ERROR]
    assert [(n.title, n.message) for n in errors] == [(TITLE, "No access to the chat; data kept")]
    assert rig.ids() == []

    await rig.worker.stop()
    assert task.done()
    assert task.exception() is None
    assert rig.ids() == []


async def test_lost_access_keeps_the_data_that_is_already_stored(make_rig: RigFactory) -> None:
    first = make_rig(range(1, 51))
    first.start()
    await first.until_complete()
    await first.shutdown()
    first.gateway.fail["iter_since"] = [AccessLost(CHAT_ID)]
    second = make_rig(gateway=first.gateway, clock=first.clock)
    second.start()
    await second.until(lambda: second.phase() == PHASE_NO_ACCESS, "no access")

    for i in range(51, 60):
        second.worker.submit(new_event(i))
    await second.settle()
    await second.worker.stop()

    assert_disk_consistent(second.folder, expect_ids=range(1, 51))


async def test_lost_access_in_the_tail_backfill_keeps_what_was_downloaded(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    fail_once_in_tail(rig, AccessLost(CHAT_ID), after=3)
    rig.start()

    await rig.until(lambda: rig.phase() == PHASE_NO_ACCESS, "no access")

    assert set(range(316, 1001)) <= set(assert_disk_consistent(rig.folder))
    assert not rig.state().backfill.done


async def test_a_refetch_request_brings_a_chat_back_from_lost_access(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 51))
    rig.gateway.fail["newest_id"] = [AccessLost(CHAT_ID)]
    rig.start()
    await rig.until(lambda: rig.phase() == PHASE_NO_ACCESS, "no access")

    rig.worker.request_refetch()
    await rig.until_complete()

    assert rig.worker.status().error is None
    assert_disk_consistent(rig.folder, expect_ids=range(1, 51))
    for i in range(51, 56):
        rig.worker.submit(new_event(i))
    await rig.until(lambda: max(rig.ids()) == 55, "live flush after recovery")


@pytest.mark.parametrize("site", ["head_newest", "catch_up", "tail"])
async def test_a_revoked_session_ends_the_run_and_notifies_without_details(
    make_rig: RigFactory, site: str
) -> None:
    rig = await prepare_site(make_rig, site, SessionRevoked("gone"))
    task = rig.start()

    with pytest.raises(SessionRevoked):
        await asyncio.wait_for(task, 3)

    assert rig.worker.status().error == "session revoked"
    errors = [n for n in rig.notifier.notes if n.level is Level.ERROR]
    assert [(n.title, n.message) for n in errors] == [
        (TITLE, "Telegram session revoked: run chatimport login")
    ]
    assert rig.worker.lock.locked() is False


@pytest.mark.parametrize("site", ["head_newest", "catch_up", "tail"])
async def test_an_unexpected_error_ends_the_run_and_a_new_run_recovers(
    make_rig: RigFactory, site: str
) -> None:
    rig = await prepare_site(make_rig, site, RuntimeError("boom"))
    task = rig.start()

    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(task, 3)

    assert rig.worker.status().error == "RuntimeError"
    assert rig.worker.lock.locked() is False
    rig.start()
    await rig.until_complete()
    assert_disk_consistent(rig.folder, expect_ids=expected_ids(site))
