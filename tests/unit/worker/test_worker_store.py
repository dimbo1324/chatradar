"""Heavy file work of the worker runs in threads and is never abandoned half-way."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from chatimport.storage.chat_store import ChatStore
from chatimport.storage.state import new_state
from chatimport.worker_store import INLINE_APPEND_RECORDS, WorkerStore, run_blocking
from tests.fakes import CHAT_ID, NOW, FakeClock, msg

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


async def test_run_blocking_runs_the_call_in_another_thread() -> None:
    main = threading.get_ident()

    assert await run_blocking(threading.get_ident) != main


async def test_run_blocking_passes_errors_through() -> None:
    def boom() -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        await run_blocking(boom)


async def test_a_cancelled_caller_waits_until_the_thread_has_finished() -> None:
    started = threading.Event()
    release = threading.Event()
    finished: list[bool] = []

    def slow() -> None:
        started.set()
        release.wait(5)
        finished.append(True)

    task = asyncio.create_task(run_blocking(slow))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished == [True]


async def test_a_cancelled_caller_of_a_failing_call_still_raises_cancelled() -> None:
    started = threading.Event()
    release = threading.Event()

    def failing() -> None:
        started.set()
        release.wait(5)
        raise OSError("late failure")

    task = asyncio.create_task(run_blocking(failing))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.01)
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task


async def test_the_event_loop_keeps_running_during_a_large_month_write(tmp_path: Path) -> None:
    store = WorkerStore(
        ChatStore(tmp_path, CHAT_ID, "chat", max_chunk_bytes=10**9, clock=FakeClock())
    )
    state = store.save(new_state(CHAT_ID, "t", None, NOW))
    messages = [msg(i, date=NOW, text="x" * 200) for i in range(1, 20001)]
    ticks = 0
    stop = asyncio.Event()

    async def ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0)

    running = asyncio.create_task(ticker())
    written = await store.merge_month(state, "2026-10", messages)
    stop.set()
    await running

    assert written.last_id == 0
    assert written.total_records == 20000
    assert ticks > 1


async def test_small_appends_stay_on_the_loop_and_big_ones_go_to_a_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    offloaded: list[int] = []
    real = run_blocking

    async def counting[T](call: Callable[[], T]) -> T:
        offloaded.append(1)
        return await real(call)

    monkeypatch.setattr("chatimport.worker_store.run_blocking", counting)
    store = WorkerStore(
        ChatStore(tmp_path, CHAT_ID, "chat", max_chunk_bytes=10**9, clock=FakeClock())
    )
    state = store.save(new_state(CHAT_ID, "t", None, NOW))

    state = await store.append(state, [msg(i) for i in range(1, INLINE_APPEND_RECORDS)])
    assert offloaded == []
    state = await store.append(
        state, [msg(i) for i in range(INLINE_APPEND_RECORDS, 2 * INLINE_APPEND_RECORDS)]
    )
    assert offloaded == [1]
    assert state.last_id == 2 * INLINE_APPEND_RECORDS - 1
    assert store.folder == tmp_path / "chat"
