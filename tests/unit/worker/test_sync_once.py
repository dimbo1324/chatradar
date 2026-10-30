"""`ChatWorker.sync_once`: the start logic of `run()` plus a full tail backfill, then return."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from chatimport.ports import AccessLost, FloodWait, SessionRevoked
from chatimport.storage.layout import list_parts
from tests.fakes import CHAT_ID, msg
from tests.unit.worker.rig import (
    Rig,
    RigFactory,
    assert_disk_consistent,
    make_rig,
    new_event,
)

__all__ = ["make_rig"]


def tail_started(rig: Rig) -> bool:
    return any(name == "iter_history" and args[1] for name, args in rig.gateway.calls)


async def test_sync_once_downloads_the_whole_history_and_returns(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 1001))

    await asyncio.wait_for(rig.worker.sync_once(), 5)

    state = rig.state()
    assert state.backfill.done
    assert state.last_id == 1000
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))
    assert [t for t in asyncio.all_tasks() if t is not asyncio.current_task()] == []


async def test_sync_once_of_an_empty_chat_completes(make_rig: RigFactory) -> None:
    rig = make_rig()

    await asyncio.wait_for(rig.worker.sync_once(), 5)

    state = rig.state()
    assert (state.backfill.done, state.last_id, state.chunks) == (True, 0, {})


async def test_sync_once_does_not_consume_live_events(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 101))
    for i in range(101, 111):
        rig.worker.submit(new_event(i))

    await asyncio.wait_for(rig.worker.sync_once(), 5)

    assert_disk_consistent(rig.folder, expect_ids=range(1, 101))


async def test_a_second_sync_once_is_idempotent(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 1001))
    await rig.worker.sync_once()
    parts = {p.name: p.read_bytes() for p in list_parts(rig.folder)}
    history_calls = rig.gateway.count("iter_history")

    await rig.worker.sync_once()

    assert {p.name: p.read_bytes() for p in list_parts(rig.folder)} == parts
    assert rig.gateway.count("iter_history") == history_calls
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_sync_once_picks_up_messages_that_arrived_since_the_last_run(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 301))
    await rig.worker.sync_once()
    for i in range(301, 351):
        rig.gateway.chats[CHAT_ID][i] = msg(i)

    await rig.worker.sync_once()

    assert_disk_consistent(rig.folder, expect_ids=range(1, 351))
    assert rig.state().last_id == 350


@pytest.mark.parametrize("cut", [1, 50, 200, 315])
async def test_a_cancelled_sync_once_leaves_consistent_files_and_the_next_one_finishes(
    make_rig: RigFactory, cut: int
) -> None:
    rig = make_rig(range(1, 1001))
    seen = 0
    holder: list[asyncio.Task[None]] = []

    def hook() -> None:
        nonlocal seen
        if not tail_started(rig):
            return
        seen += 1
        if seen == cut:
            holder[0].cancel()
            raise asyncio.CancelledError

    rig.gateway.page_hook = hook
    holder.append(asyncio.create_task(rig.worker.sync_once()))
    with pytest.raises(asyncio.CancelledError):
        await holder[0]
    assert not rig.state().backfill.done
    assert_disk_consistent(rig.folder)

    rig.gateway.page_hook = None
    await asyncio.wait_for(rig.worker.sync_once(), 5)

    assert rig.state().backfill.done
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_sync_once_waits_out_a_flood_wait_in_the_tail(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 1001))
    fired = False

    def hook() -> None:
        nonlocal fired
        if tail_started(rig) and not fired:
            fired = True
            raise FloodWait(42)

    rig.gateway.page_hook = hook

    await asyncio.wait_for(rig.worker.sync_once(), 5)

    assert 42 in rig.clock.sleeps
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_sync_once_starts_over_when_the_folder_disappears_mid_tail(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 1001))
    seen = 0

    def hook() -> None:
        nonlocal seen
        if tail_started(rig):
            seen += 1
            if seen == 10:
                shutil.rmtree(rig.folder)

    rig.gateway.page_hook = hook

    await asyncio.wait_for(rig.worker.sync_once(), 5)

    assert 20 in rig.clock.sleeps
    assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))


async def test_sync_once_raises_when_the_session_is_revoked(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 11))
    rig.gateway.fail["newest_id"] = [SessionRevoked()]

    with pytest.raises(SessionRevoked):
        await asyncio.wait_for(rig.worker.sync_once(), 3)

    assert rig.worker.status().error == "session revoked"


async def test_sync_once_does_not_wait_forever_for_events_when_access_is_lost(
    make_rig: RigFactory,
) -> None:
    rig = make_rig(range(1, 11))
    rig.gateway.fail["newest_id"] = [AccessLost(CHAT_ID)]

    try:
        await asyncio.wait_for(rig.worker.sync_once(), 0.5)
    except AccessLost:
        pass
    except TimeoutError:
        pytest.fail("sync_once hangs in the lost-access state instead of ending")


async def test_sync_once_propagates_unexpected_errors(make_rig: RigFactory) -> None:
    rig = make_rig(range(1, 11))
    rig.gateway.fail["iter_history"] = [ValueError("bad page")]

    with pytest.raises(ValueError, match="bad page"):
        await rig.worker.sync_once()

    await rig.worker.sync_once()
    assert_disk_consistent(rig.folder, expect_ids=range(1, 11))
