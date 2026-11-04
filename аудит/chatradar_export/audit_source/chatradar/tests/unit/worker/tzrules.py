"""Minimal DST-aware time zones for tests, so they do not depend on the `tzdata` package
(Windows ships no IANA database and the project has no `tzdata` dependency).

The rules are the 2026 rules of Europe/Madrid and America/New_York.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

ZERO = timedelta(0)


def nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def last_sunday(year: int, month: int) -> date:
    following = date(year + (month == 12), month % 12 + 1, 1)
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def at_utc(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour)  # noqa: DTZ001


class RuleZone(tzinfo):
    """Standard offset plus one DST window given in naive UTC."""

    def __init__(
        self,
        name: str,
        standard: timedelta,
        saving: timedelta,
        window: Callable[[int], tuple[datetime, datetime]],
    ) -> None:
        self._name = name
        self._standard = standard
        self._saving = saving
        self._window = window

    def _in_dst(self, utc_naive: datetime) -> bool:
        start, end = self._window(utc_naive.year)
        return start <= utc_naive < end

    def fromutc(self, dt: datetime) -> datetime:
        utc_naive = dt.replace(tzinfo=None)
        dst = self._in_dst(utc_naive)
        offset = self._standard + (self._saving if dst else ZERO)
        _, end = self._window(utc_naive.year)
        second_pass = not dst and end <= utc_naive < end + self._saving
        return (utc_naive + offset).replace(tzinfo=self, fold=int(second_pass))

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        wall = dt.replace(tzinfo=None)
        std_valid = not self._in_dst(wall - self._standard)
        dst_valid = self._in_dst(wall - self._standard - self._saving)
        if dst_valid and not std_valid:
            return self._standard + self._saving
        if std_valid and not dst_valid:
            return self._standard
        if dst_valid and std_valid:
            return self._standard if dt.fold else self._standard + self._saving
        return self._standard + self._saving if dt.fold else self._standard

    def dst(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        return self.utcoffset(dt) - self._standard

    def tzname(self, dt: datetime | None) -> str:
        return self._name


def _us_window(year: int) -> tuple[datetime, datetime]:
    return at_utc(nth_sunday(year, 3, 2), 7), at_utc(nth_sunday(year, 11, 1), 6)


def _eu_window(year: int) -> tuple[datetime, datetime]:
    return at_utc(last_sunday(year, 3), 1), at_utc(last_sunday(year, 10), 1)


NEW_YORK = RuleZone("America/New_York", timedelta(hours=-5), timedelta(hours=1), _us_window)
MADRID = RuleZone("Europe/Madrid", timedelta(hours=1), timedelta(hours=1), _eu_window)
MONTEVIDEO = timezone(timedelta(hours=-3), "America/Montevideo")
