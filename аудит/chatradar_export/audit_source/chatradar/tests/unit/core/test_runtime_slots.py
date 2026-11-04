from __future__ import annotations

import asyncio
import logging

import pytest

from chatimport.runtime import BackfillSlots, Level, LogNotifier


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def test_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        BackfillSlots(0)
    assert BackfillSlots(3).limit == 3


async def run_chats(limit: int, chats: int) -> tuple[int, list[int]]:
    slots = BackfillSlots(limit)
    active = 0
    peak = 0
    order: list[int] = []
    release = asyncio.Event()

    async def backfill(chat_id: int) -> None:
        nonlocal active, peak
        async with slots.acquire(chat_id):
            order.append(chat_id)
            active += 1
            peak = max(peak, active)
            await release.wait()
            active -= 1

    tasks = [asyncio.create_task(backfill(chat_id)) for chat_id in range(chats)]
    await settle()
    assert active == min(limit, chats)
    release.set()
    await asyncio.gather(*tasks)
    return peak, order


@pytest.mark.parametrize(("limit", "expected_peak"), [(1, 1), (2, 2), (5, 3)])
async def test_at_most_limit_chats_hold_a_slot(limit: int, expected_peak: int) -> None:
    peak, order = await run_chats(limit, 3)
    assert peak == expected_peak
    assert order == [0, 1, 2]


async def test_waiting_chats_get_the_slot_in_arrival_order() -> None:
    slots = BackfillSlots(1)
    entered: list[int] = []
    gate = asyncio.Event()

    async def chat(chat_id: int) -> None:
        async with slots.acquire(chat_id):
            entered.append(chat_id)
            await gate.wait()

    first = asyncio.create_task(chat(1))
    await settle()
    waiters = [asyncio.create_task(chat(n)) for n in (5, 3, 4)]
    await settle()
    assert slots.holders == (1,)
    assert slots.waiting == (5, 3, 4)
    gate.set()
    await asyncio.gather(first, *waiters)
    assert entered == [1, 5, 3, 4]
    assert slots.holders == ()


async def test_a_chat_holding_a_slot_may_enter_again_without_waiting() -> None:
    slots = BackfillSlots(1)
    async with slots.acquire(7), slots.acquire(7):
        assert slots.holders == (7,)
    assert slots.holders == ()


async def test_a_cancelled_waiter_gives_up_its_place() -> None:
    slots = BackfillSlots(1)
    gate = asyncio.Event()
    entered: list[int] = []

    async def chat(chat_id: int) -> None:
        async with slots.acquire(chat_id):
            entered.append(chat_id)
            await gate.wait()

    holder = asyncio.create_task(chat(1))
    await settle()
    cancelled = asyncio.create_task(chat(2))
    later = asyncio.create_task(chat(3))
    await settle()
    cancelled.cancel()
    await settle()
    assert slots.waiting == (3,)
    gate.set()
    await asyncio.gather(holder, later)
    assert cancelled.cancelled()
    assert entered == [1, 3]


async def test_cancel_after_the_slot_was_handed_over_passes_it_on() -> None:
    slots = BackfillSlots(1)
    entered: list[int] = []

    async def chat(chat_id: int) -> None:
        async with slots.acquire(chat_id):
            entered.append(chat_id)

    holding = slots.acquire(1)
    await holding.__aenter__()
    second = asyncio.create_task(chat(2))
    third = asyncio.create_task(chat(3))
    await settle()
    await holding.__aexit__(None, None, None)
    assert slots.holders == (2,)
    second.cancel()
    await asyncio.gather(second, third, return_exceptions=True)
    assert second.cancelled()
    assert entered == [3]
    assert slots.holders == ()


async def test_a_second_waiter_of_a_chat_that_got_a_slot_joins_that_slot() -> None:
    slots = BackfillSlots(2)
    gates = {chat_id: asyncio.Event() for chat_id in (1, 9, 2)}
    inside: list[tuple[int, ...]] = []

    async def chat(chat_id: int) -> None:
        async with slots.acquire(chat_id):
            inside.append(slots.holders)
            await gates[chat_id].wait()

    holders = [asyncio.create_task(chat(1)), asyncio.create_task(chat(9))]
    await settle()
    twins = [asyncio.create_task(chat(2)), asyncio.create_task(chat(2))]
    await settle()
    gates[1].set()
    await settle()
    gates[9].set()
    await settle()
    assert slots.holders == (2,)
    assert inside[-2:] == [(9, 2), (2,)]
    gates[2].set()
    await asyncio.gather(*holders, *twins)
    assert slots.holders == ()


@pytest.mark.parametrize(
    ("level", "expected"),
    [(Level.INFO, logging.INFO), (Level.WARNING, logging.WARNING), (Level.ERROR, logging.ERROR)],
)
def test_level_maps_to_the_logging_level(
    level: Level, expected: int, caplog: pytest.LogCaptureFixture
) -> None:
    assert level.logging_level == expected
    with caplog.at_level(logging.DEBUG, logger="chatimport.notify"):
        LogNotifier().notify(level, "Title", "body")
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [(expected, "Title: body")]
