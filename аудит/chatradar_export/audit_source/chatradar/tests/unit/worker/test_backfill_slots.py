"""History downloads share `BackfillSlots`: at most `max_parallel_chats` chats at once."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from chatimport.runtime import BackfillSlots
from chatimport.worker_backfill import SlotHolder
from tests.fakes import CHAT_ID, FakeClock, FakeGateway
from tests.unit.worker.rig import RigFactory, assert_disk_consistent, make_rig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from chatimport.records import MessageRecord

__all__ = ["make_rig"]

OTHER = CHAT_ID + 7


class SlotCheckingGateway(FakeGateway):
    """Notes, at every history message it hands out, which chats hold a slot."""

    def __init__(self, slots: BackfillSlots) -> None:
        super().__init__()
        self.slots = slots
        self.outside: list[int] = []
        self.most_holders = 0

    async def iter_history(
        self, chat_id: int, *, offset_id: int = 0, min_id: int = 0
    ) -> AsyncIterator[MessageRecord]:
        async for record in super().iter_history(chat_id, offset_id=offset_id, min_id=min_id):
            holders = self.slots.holders
            if chat_id not in holders:
                self.outside.append(chat_id)
            self.most_holders = max(self.most_holders, len(holders))
            yield record
            await asyncio.sleep(0)


@pytest.mark.parametrize("limit", [1, 2])
async def test_history_downloads_run_at_most_max_parallel_chats_at_once(
    make_rig: RigFactory, limit: int
) -> None:
    slots = BackfillSlots(limit)
    gateway = SlotCheckingGateway(slots)
    clock = FakeClock()
    rigs = [
        make_rig(
            range(1, 1001),
            chat_id=chat_id,
            title=f"Chat {n}",
            gateway=gateway,
            clock=clock,
            slots=slots,
        )
        for n, chat_id in enumerate((CHAT_ID, OTHER))
    ]
    for rig in rigs:
        rig.start()
    for rig in rigs:
        await rig.until_complete()

    assert gateway.outside == []
    assert gateway.most_holders == limit
    for rig in rigs:
        assert_disk_consistent(rig.folder, expect_ids=range(1, 1001))
    assert slots.holders == ()


async def test_a_chat_with_a_paused_backfill_lets_the_others_download(
    make_rig: RigFactory,
) -> None:
    slots = BackfillSlots(1)
    gateway = FakeGateway()
    clock = FakeClock()
    paused = make_rig(range(1, 1001), gateway=gateway, clock=clock, slots=slots)
    other = make_rig(
        range(1, 1001), chat_id=OTHER, title="Other", gateway=gateway, clock=clock, slots=slots
    )
    paused.worker.pause_backfill()
    paused.start()
    await paused.until_live()
    other.start()

    await other.until_complete()
    assert not paused.backfill_done()

    paused.worker.resume_backfill()
    await paused.until_complete()
    assert_disk_consistent(paused.folder, expect_ids=range(1, 1001))


async def test_a_paused_head_backfill_gives_its_slot_back(make_rig: RigFactory) -> None:
    slots = BackfillSlots(1)
    gateway = FakeGateway()
    clock = FakeClock()
    rig = make_rig(
        range(1, 401),
        gateway=gateway,
        clock=clock,
        slots=slots,
    )
    seen = 0

    def hook() -> None:
        nonlocal seen
        seen += 1
        if seen == 150:
            rig.worker.pause()

    gateway.page_hook = hook
    rig.start()
    await rig.until(lambda: rig.phase() == "paused", "parked inside the head backfill")

    assert slots.holders == ()
    gateway.page_hook = None
    rig.worker.resume()
    await rig.until_complete()
    assert_disk_consistent(rig.folder, expect_ids=range(1, 401))


async def test_a_slot_holder_without_slots_does_nothing() -> None:
    holder = SlotHolder(None, CHAT_ID)

    async with holder.holding():
        assert not holder.held
        async with holder.suspended():
            assert not holder.held


async def test_a_slot_holder_takes_its_slot_back_after_a_suspension() -> None:
    slots = BackfillSlots(1)
    holder = SlotHolder(slots, CHAT_ID)

    async with holder.holding():
        await holder.acquire()
        assert slots.holders == (CHAT_ID,)
        async with holder.suspended():
            assert slots.holders == ()
        assert holder.held
    assert slots.holders == ()


async def test_a_slot_is_not_taken_back_when_the_suspended_body_fails() -> None:
    slots = BackfillSlots(1)
    holder = SlotHolder(slots, CHAT_ID)

    with pytest.raises(RuntimeError):
        async with holder.holding(), holder.suspended():
            raise RuntimeError("stop")

    assert not holder.held
    assert slots.holders == ()
