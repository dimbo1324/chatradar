"""`seconds_until_next` across DST transitions and `RecheckScheduler` pacing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

import pytest

from chatimport.config import RecheckConfig
from chatimport.recheck import STARTUP_STALE_AFTER, RecheckScheduler, seconds_until_next
from chatimport.runtime import ChatRegistry, ChatStatus
from tests.fakes import NOW, FakeClock
from tests.unit.worker.tzrules import MADRID, MONTEVIDEO, NEW_YORK

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import ChatEvent

HOUR = 3600.0


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0, micro: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "tz", "daily_at", "expected"),
    [
        pytest.param(utc(2026, 10, 29, 12), MONTEVIDEO, "04:00", 19 * HOUR, id="plain-day"),
        pytest.param(utc(2026, 10, 29, 12), MADRID, "04:00", 15 * HOUR, id="madrid-after-fall"),
        pytest.param(utc(2026, 10, 29, 7), MONTEVIDEO, "04:00", 24 * HOUR, id="exactly-at-target"),
        pytest.param(
            utc(2026, 10, 29, 7, 0, 0, micro=1),
            MONTEVIDEO,
            "04:00",
            24 * HOUR - 1e-6,
            id="one-microsecond-after-target",
        ),
        pytest.param(
            utc(2026, 10, 29, 6, 59, 59), MONTEVIDEO, "04:00", 1.0, id="one-second-before"
        ),
        pytest.param(utc(2026, 10, 29, 12), MONTEVIDEO, "4:00", 19 * HOUR, id="single-digit-hour"),
        pytest.param(utc(2026, 10, 29, 2, 59), MONTEVIDEO, "00:00", 60.0, id="midnight-target"),
        pytest.param(utc(2026, 10, 29, 12), UTC, "23:59", 11 * HOUR + 59 * 60, id="utc-late"),
        pytest.param(
            utc(2026, 3, 28, 3, 30), MADRID, "04:00", 22.5 * HOUR, id="madrid-spring-forward"
        ),
        pytest.param(utc(2026, 10, 24, 2, 30), MADRID, "04:00", 24.5 * HOUR, id="madrid-fall-back"),
        pytest.param(
            utc(2026, 3, 7, 10), NEW_YORK, "04:00", 22 * HOUR, id="new-york-spring-forward"
        ),
        pytest.param(utc(2026, 10, 31, 9), NEW_YORK, "04:00", 24 * HOUR, id="new-york-fall-back"),
        pytest.param(
            utc(2026, 11, 1, 4), NEW_YORK, "01:30", 1.5 * HOUR, id="before-the-ambiguous-hour"
        ),
    ],
)
def test_seconds_until_next_is_the_real_elapsed_time(
    now: datetime, tz: tzinfo, daily_at: str, expected: float
) -> None:
    assert seconds_until_next(daily_at, now, tz) == pytest.approx(expected, abs=1e-6)


def test_the_same_instant_in_any_offset_gives_the_same_answer() -> None:
    instant = utc(2026, 10, 29, 12)
    tokyo = instant.astimezone(timezone(timedelta(hours=9)))

    assert seconds_until_next("04:00", tokyo, MONTEVIDEO) == seconds_until_next(
        "04:00", instant, MONTEVIDEO
    )


@pytest.mark.parametrize("daily_at", ["", "ab:cd", "24:00", "12:60", "-1:00", "04", "04:00:30"])
def test_seconds_until_next_rejects_malformed_times(daily_at: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        seconds_until_next(daily_at, NOW, UTC)


@pytest.mark.parametrize("daily_at", ["02:30", "02:00", "03:00"])
def test_a_time_that_does_not_exist_on_a_spring_forward_day_still_gives_a_sane_wait(
    daily_at: str,
) -> None:
    wait = seconds_until_next(daily_at, utc(2026, 3, 8, 5), NEW_YORK)

    assert 0 < wait <= 25 * HOUR


@pytest.mark.parametrize(
    ("tz", "start"),
    [
        pytest.param(MADRID, utc(2026, 3, 27), id="madrid-spring"),
        pytest.param(MADRID, utc(2026, 10, 23), id="madrid-autumn"),
        pytest.param(NEW_YORK, utc(2026, 3, 6), id="new-york-spring"),
        pytest.param(NEW_YORK, utc(2026, 10, 30), id="new-york-autumn"),
        pytest.param(MONTEVIDEO, utc(2026, 10, 27), id="montevideo"),
    ],
)
@pytest.mark.parametrize("daily_at", ["04:00", "12:00", "00:00", "23:59", "04:30"])
def test_the_wait_always_lands_on_the_requested_local_time(
    tz: tzinfo, start: datetime, daily_at: str
) -> None:
    hour, minute = (int(p) for p in daily_at.split(":"))
    for step in range(0, 5 * 24 * 60, 17):
        now = start + timedelta(minutes=step)
        wait = seconds_until_next(daily_at, now, tz)

        assert 0 < wait <= 25 * HOUR, now
        landing = (now + timedelta(seconds=wait)).astimezone(tz)
        assert (landing.hour, landing.minute, landing.second) == (hour, minute, 0), (now, wait)


class StubController:
    def __init__(self, chat_id: int, folder: Path) -> None:
        self._chat_id = chat_id
        self._folder = folder
        self._lock = asyncio.Lock()
        self.rechecks: list[int | None] = []

    @property
    def chat_id(self) -> int:
        return self._chat_id

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def submit(self, event: ChatEvent) -> None:
        return None

    def pause(self) -> None:
        return None

    def resume(self) -> None:
        return None

    def pause_backfill(self) -> None:
        return None

    def resume_backfill(self) -> None:
        return None

    def request_refetch(self) -> None:
        return None

    def request_recheck(self, days: int | None = None) -> None:
        self.rechecks.append(days)

    def status(self) -> ChatStatus:
        return ChatStatus(self._chat_id, "t", "live", 0, True, None, 0, False)

    async def stop(self) -> None:
        return None


class StopLoop(Exception):
    pass


def make_scheduler(
    tmp_path: Path,
    count: int,
    last: dict[int, datetime | None],
    *,
    config: RecheckConfig | None = None,
    stop_after_sleeps: int = 100,
) -> tuple[RecheckScheduler, list[StubController], FakeClock]:
    registry = ChatRegistry()
    controllers = [StubController(i, tmp_path) for i in range(1, count + 1)]
    for controller in controllers:
        registry.add(controller)
    clock = FakeClock()

    def on_sleep(_: float) -> None:
        if len(clock.sleeps) >= stop_after_sleeps:
            raise StopLoop

    clock.on_sleep = on_sleep
    scheduler = RecheckScheduler(
        registry,
        config or RecheckConfig(),
        clock,
        lambda c: last.get(c.chat_id),
        UTC,
    )
    return scheduler, controllers, clock


async def test_a_disabled_recheck_never_asks_or_sleeps(tmp_path: Path) -> None:
    scheduler, controllers, clock = make_scheduler(
        tmp_path, 3, {}, config=RecheckConfig(enabled=False)
    )

    await scheduler.run()

    assert all(c.rechecks == [] for c in controllers)
    assert clock.sleeps == []


async def test_startup_asks_only_chats_whose_last_recheck_is_older_than_a_day(
    tmp_path: Path,
) -> None:
    last: dict[int, datetime | None] = {
        1: None,
        2: NOW - timedelta(hours=25),
        3: NOW - timedelta(hours=23),
        4: NOW - STARTUP_STALE_AFTER,
        5: NOW - STARTUP_STALE_AFTER - timedelta(seconds=1),
        6: NOW + timedelta(hours=1),
    }
    scheduler, controllers, clock = make_scheduler(tmp_path, 6, last, stop_after_sleeps=3)

    with pytest.raises(StopLoop):
        await scheduler.run()

    asked = [c.chat_id for c in controllers if c.rechecks]
    assert asked == [1, 2, 5]
    assert clock.sleeps == [10, 10, 57580]
    assert all(c.rechecks == [7] for c in controllers if c.chat_id in asked)


async def test_the_daily_pass_asks_every_chat_in_registry_order_with_pauses(
    tmp_path: Path,
) -> None:
    fresh: dict[int, datetime | None] = dict.fromkeys(range(1, 5), NOW)
    config = RecheckConfig(pause_between_chats_sec=3, days=2, daily_at="04:00")
    scheduler, controllers, clock = make_scheduler(
        tmp_path, 4, fresh, config=config, stop_after_sleeps=5
    )

    with pytest.raises(StopLoop):
        await scheduler.run()

    assert clock.sleeps[0] == 16 * HOUR
    assert clock.sleeps[1:4] == [3, 3, 3]
    assert clock.sleeps[4] == pytest.approx(24 * HOUR - 9)
    assert all(c.rechecks == [2] for c in controllers)


async def test_a_single_chat_pass_has_no_pause(tmp_path: Path) -> None:
    scheduler, controllers, clock = make_scheduler(tmp_path, 1, {}, stop_after_sleeps=1)

    with pytest.raises(StopLoop):
        await scheduler.run()

    assert controllers[0].rechecks == [7]
    assert clock.sleeps == [16 * HOUR]


async def test_without_chats_the_scheduler_just_waits_for_the_next_day(tmp_path: Path) -> None:
    scheduler, _, clock = make_scheduler(tmp_path, 0, {}, stop_after_sleeps=2)

    with pytest.raises(StopLoop):
        await scheduler.run()

    assert clock.sleeps == [16 * HOUR, 24 * HOUR]


async def test_the_default_timezone_is_the_system_one(tmp_path: Path) -> None:
    registry = ChatRegistry()
    clock = FakeClock()

    def on_sleep(_: float) -> None:
        raise StopLoop

    clock.on_sleep = on_sleep
    scheduler = RecheckScheduler(registry, RecheckConfig(), clock, lambda _c: None)

    with pytest.raises(StopLoop):
        await scheduler.run()

    assert 0 < clock.sleeps[0] <= 25 * HOUR
    del tmp_path


async def test_trigger_now_asks_every_chat_regardless_of_enabled(tmp_path: Path) -> None:
    scheduler, controllers, clock = make_scheduler(
        tmp_path, 3, {}, config=RecheckConfig(enabled=False, pause_between_chats_sec=4)
    )

    asked = await scheduler.trigger_now()

    assert asked == 3
    assert all(c.rechecks == [7] for c in controllers)
    assert clock.sleeps == [4, 4]


async def test_trigger_now_can_override_the_window_and_target_one_chat(tmp_path: Path) -> None:
    scheduler, controllers, clock = make_scheduler(tmp_path, 3, {})

    asked = await scheduler.trigger_now(days=30, chat_id=2)

    assert asked == 1
    assert [c.rechecks for c in controllers] == [[], [30], []]
    assert clock.sleeps == []


async def test_trigger_now_for_an_unknown_chat_asks_nobody(tmp_path: Path) -> None:
    scheduler, controllers, clock = make_scheduler(tmp_path, 2, {})

    assert await scheduler.trigger_now(chat_id=99) == 0
    assert all(c.rechecks == [] for c in controllers)
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("instant", "zone", "wall", "fold"),
    [
        (utc(2026, 3, 29, 0, 59, 59), MADRID, (1, 59, 59), 0),
        (utc(2026, 3, 29, 1), MADRID, (3, 0, 0), 0),
        (utc(2026, 10, 25, 0, 59, 59), MADRID, (2, 59, 59), 0),
        (utc(2026, 10, 25, 1), MADRID, (2, 0, 0), 1),
        (utc(2026, 3, 8, 6, 59, 59), NEW_YORK, (1, 59, 59), 0),
        (utc(2026, 3, 8, 7), NEW_YORK, (3, 0, 0), 0),
        (utc(2026, 11, 1, 5, 59, 59), NEW_YORK, (1, 59, 59), 0),
        (utc(2026, 11, 1, 6), NEW_YORK, (1, 0, 0), 1),
    ],
)
def test_the_test_zones_follow_the_2026_transition_rules(
    instant: datetime, zone: tzinfo, wall: tuple[int, int, int], fold: int
) -> None:
    local = instant.astimezone(zone)

    assert (local.hour, local.minute, local.second, local.fold) == (*wall, fold)
    assert local.astimezone(UTC) == instant
