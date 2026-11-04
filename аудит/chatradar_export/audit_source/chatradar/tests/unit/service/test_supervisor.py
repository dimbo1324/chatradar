from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from chatimport import supervisor as supervisor_module
from chatimport.ports import SessionRevoked
from chatimport.runtime import Level
from chatimport.supervisor import FIRST_DELAY, MAX_DELAY, STABLE_AFTER, Supervisor
from tests.fakes import FakeClock, RecordingNotifier

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class Monotonic:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def mono(monkeypatch: pytest.MonkeyPatch) -> Monotonic:
    fake = Monotonic()
    monkeypatch.setattr(supervisor_module, "time", SimpleNamespace(monotonic=fake))
    return fake


def make() -> tuple[Supervisor, FakeClock, RecordingNotifier]:
    clock, notifier = FakeClock(), RecordingNotifier()
    return Supervisor(clock, notifier), clock, notifier


def failing_times(
    count: int, *, run_for: Callable[[int], float] | None = None, mono: Monotonic | None = None
) -> tuple[Callable[[], Awaitable[None]], list[int]]:
    calls: list[int] = []

    async def factory() -> None:
        calls.append(len(calls) + 1)
        if mono is not None and run_for is not None:
            mono.value += run_for(len(calls))
        if len(calls) <= count:
            raise RuntimeError(f"failure {len(calls)}")

    return factory, calls


async def test_backoff_doubles_from_one_second_up_to_the_cap(mono: Monotonic) -> None:
    supervisor, clock, _ = make()
    factory, calls = failing_times(14)

    await supervisor.spawn("t", factory)

    assert len(calls) == 15
    assert clock.sleeps == [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 300, 300, 300, 300]
    assert max(clock.sleeps) == MAX_DELAY
    assert clock.sleeps[0] == FIRST_DELAY


async def test_delay_resets_after_a_run_of_exactly_the_stable_period(mono: Monotonic) -> None:
    supervisor, clock, _ = make()
    lengths = {1: 0, 2: 0, 3: 0, 4: STABLE_AFTER, 5: 0}
    factory, _ = failing_times(5, run_for=lambda n: lengths.get(n, 0), mono=mono)

    await supervisor.spawn("t", factory)

    assert clock.sleeps == [1, 2, 4, 1, 2]


async def test_delay_is_kept_when_the_run_was_just_short_of_stable(mono: Monotonic) -> None:
    supervisor, clock, _ = make()
    lengths = {1: 0, 2: 0, 3: STABLE_AFTER - 0.001, 4: 0}
    factory, _ = failing_times(4, run_for=lambda n: lengths.get(n, 0), mono=mono)

    await supervisor.spawn("t", factory)

    assert clock.sleeps == [1, 2, 4, 8]


async def test_error_is_recorded_while_waiting_and_cleared_after_recovery(
    mono: Monotonic,
) -> None:
    supervisor, clock, _ = make()
    factory, _ = failing_times(1)
    seen: list[dict[str, str]] = []
    clock.on_sleep = lambda _seconds: seen.append(supervisor.errors())

    await supervisor.spawn("t", factory)

    assert seen == [{"t": "RuntimeError: failure 1"}]
    assert supervisor.errors() == {}


async def test_restart_false_stops_after_the_first_failure_and_keeps_the_error(
    mono: Monotonic,
) -> None:
    supervisor, clock, _ = make()
    factory, calls = failing_times(5)

    await supervisor.spawn("t", factory, restart=False)

    assert len(calls) == 1
    assert clock.sleeps == []
    assert supervisor.errors() == {"t": "RuntimeError: failure 1"}


async def test_normal_return_ends_the_task_and_clears_an_earlier_error(mono: Monotonic) -> None:
    supervisor, _, _ = make()
    factory, calls = failing_times(0)

    await supervisor.spawn("t", factory)

    assert calls == [1]
    assert supervisor.errors() == {}


async def test_cancellation_is_not_a_failure(mono: Monotonic) -> None:
    supervisor, clock, notifier = make()
    started = asyncio.Event()

    async def factory() -> None:
        started.set()
        await asyncio.Event().wait()

    task = supervisor.spawn("t", factory)
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert supervisor.errors() == {}
    assert clock.sleeps == []
    assert notifier.notes == []
    assert supervisor.fatal is None


async def test_session_revoked_is_fatal_notified_and_not_retried(
    mono: Monotonic, caplog: pytest.LogCaptureFixture
) -> None:
    supervisor, clock, notifier = make()
    calls = 0

    async def factory() -> None:
        nonlocal calls
        calls += 1
        raise SessionRevoked("gone")

    with caplog.at_level(logging.ERROR):
        await supervisor.spawn("worker", factory)

    assert calls == 1
    assert clock.sleeps == []
    assert isinstance(supervisor.fatal, SessionRevoked)
    assert supervisor.fatal_event.is_set()
    assert supervisor.errors() == {"worker": "SessionRevoked: gone"}
    assert len(notifier.notes) == 1
    assert notifier.notes[0].level is Level.ERROR
    assert "login" in notifier.notes[0].message


async def test_wait_fatal_returns_once_a_task_hit_session_revoked(mono: Monotonic) -> None:
    supervisor, _, _ = make()

    async def factory() -> None:
        raise SessionRevoked("gone")

    waiter = asyncio.create_task(supervisor.wait_fatal())
    await asyncio.sleep(0)
    assert not waiter.done()
    supervisor.spawn("w", factory)
    await asyncio.wait_for(waiter, 1)


async def test_ordinary_failures_do_not_set_fatal(mono: Monotonic) -> None:
    supervisor, _, _ = make()
    factory, _ = failing_times(2)

    await supervisor.spawn("t", factory)

    assert supervisor.fatal is None
    assert not supervisor.fatal_event.is_set()


async def test_errors_returns_a_copy(mono: Monotonic) -> None:
    supervisor, _, _ = make()
    factory, _ = failing_times(1)
    await supervisor.spawn("t", factory, restart=False)

    snapshot = supervisor.errors()
    snapshot["x"] = "y"

    assert "x" not in supervisor.errors()


async def test_a_failing_task_does_not_disturb_its_neighbour(mono: Monotonic) -> None:
    supervisor, _, _ = make()
    healthy_runs: list[int] = []
    release = asyncio.Event()

    async def healthy() -> None:
        healthy_runs.append(1)
        await release.wait()

    bad, _ = failing_times(3)
    good = supervisor.spawn("good", healthy)
    await supervisor.spawn("bad", bad)

    assert not good.done()
    assert healthy_runs == [1]
    release.set()
    await good


async def test_stop_all_cancels_sleeping_and_running_tasks_and_forgets_them(
    mono: Monotonic,
) -> None:
    supervisor = Supervisor(SleepyClock(), RecordingNotifier())
    running = asyncio.Event()

    async def blocked() -> None:
        running.set()
        await asyncio.Event().wait()

    async def failing() -> None:
        raise RuntimeError("x")

    first = supervisor.spawn("blocked", blocked)
    second = supervisor.spawn("backoff", failing)
    await running.wait()
    await asyncio.sleep(0.01)

    await supervisor.stop_all()

    assert first.cancelled()
    assert second.cancelled()
    await supervisor.stop_all()


async def test_stop_all_on_an_empty_supervisor_is_a_noop() -> None:
    supervisor, _, _ = make()

    await supervisor.stop_all()


async def test_stop_all_survives_tasks_that_already_finished_with_an_error(
    mono: Monotonic,
) -> None:
    supervisor, _, _ = make()
    factory, _ = failing_times(1)
    await supervisor.spawn("t", factory, restart=False)

    await supervisor.stop_all()


async def test_spawning_the_same_name_twice_keeps_both_tasks_stoppable(
    mono: Monotonic,
) -> None:
    supervisor = Supervisor(SleepyClock(), RecordingNotifier())

    async def blocked() -> None:
        await asyncio.Event().wait()

    first = supervisor.spawn("same", blocked)
    second = supervisor.spawn("same", blocked)
    await asyncio.sleep(0)

    await supervisor.stop_all()

    assert first.done()
    assert second.done()


class SleepyClock(FakeClock):
    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        await asyncio.Event().wait()


async def test_error_of_a_task_that_restarted_and_runs_healthy_is_not_reported_forever(
    mono: Monotonic,
) -> None:
    supervisor, _, _ = make()
    attempts = 0
    healthy = asyncio.Event()
    release = asyncio.Event()

    async def factory() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        healthy.set()
        await release.wait()

    task = supervisor.spawn("worker", factory)
    await healthy.wait()
    errors = supervisor.errors()
    release.set()
    await task

    assert errors == {}
