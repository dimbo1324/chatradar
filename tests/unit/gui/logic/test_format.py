from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from chatimport.gui.format import (
    DAY,
    Freshness,
    FreshnessThresholds,
    _split_age,  # pyright: ignore[reportPrivateUsage]
    classify,
    count_phrase,
    format_ago,
    format_bytes,
    format_count,
    format_exact,
    format_percent,
    humanize_age,
    zone_label,
)
from chatimport.gui.strings import Language, translate

NBSP = chr(0xA0)


def ru(key: str) -> str:
    return translate("ru", key)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "unknown"),
        (float("nan"), "unknown"),
        (-1, "unknown"),
        (0, "just now"),
        (4.9, "just now"),
        (5, "5 s"),
        (42, "42 s"),
        (59, "59 s"),
        (60, "1 min"),
        (65, "1 min 5 s"),
        (725, "12 min 5 s"),
        (3_600, "1 h"),
        (3_660, "1 h 1 min"),
        (DAY, "1 d"),
        (DAY + 3_600, "1 d 1 h"),
        (2 * DAY + 4 * 3_600, "2 d 4 h"),
        (7 * DAY, "1 wk"),
        (9 * DAY, "1 wk 2 d"),
        (30 * DAY, "1 mo"),
        (45 * DAY, "1 mo 2 wk"),
        (365 * DAY, "1 y"),
        (365 * DAY + 90 * DAY, "1 y 3 mo"),
        (365 * DAY + 360 * DAY, "1 y 11 mo"),
        (3 * 365 * DAY, "3 y"),
    ],
)
def test_humanize_age_english(seconds: float | None, expected: str) -> None:
    assert humanize_age(seconds, "en") == expected


@pytest.mark.parametrize(
    ("seconds", "parts"),
    [
        (None, ["time.unknown"]),
        (3, ["time.just_now"]),
        (42, ["42 ", "time.s"]),
        (725, ["12 ", "time.min", " 5 ", "time.s"]),
        (2 * DAY + 4 * 3_600, ["2 ", "time.d", " 4 ", "time.h"]),
        (365 * DAY + 90 * DAY, ["1 ", "time.y", " 3 ", "time.mo"]),
    ],
)
def test_humanize_age_russian_uses_catalogue_units(seconds: float | None, parts: list[str]) -> None:
    expected = "".join(ru(part) if part.startswith("time.") else part for part in parts)
    assert humanize_age(seconds, "ru") == expected
    assert humanize_age(seconds, "ru") != humanize_age(seconds, "en") or seconds is None


def test_split_age_of_zero_is_zero_seconds() -> None:
    assert _split_age(0) == [("s", 0)]


@pytest.mark.parametrize(
    ("seconds", "language", "expected"),
    [
        (None, "en", "unknown"),
        (float("nan"), "en", "unknown"),
        (2, "en", "just now"),
        (65, "en", "1 min 5 s ago"),
        (DAY, "en", "1 d ago"),
    ],
)
def test_format_ago(seconds: float | None, language: Language, expected: str) -> None:
    assert format_ago(seconds, language) == expected


def test_format_ago_russian() -> None:
    assert format_ago(65, "ru") == f"1 {ru('time.min')} 5 {ru('time.s')} {ru('time.ago')[6:]}"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, Freshness.UNKNOWN),
        (float("nan"), Freshness.UNKNOWN),
        (-0.1, Freshness.UNKNOWN),
        (0, Freshness.FRESH),
        (299.9, Freshness.FRESH),
        (300, Freshness.RECENT),
        (3_599, Freshness.RECENT),
        (3_600, Freshness.STALE),
        (DAY - 1, Freshness.STALE),
        (DAY, Freshness.DORMANT),
        (10 * DAY, Freshness.DORMANT),
    ],
)
def test_classify_default_thresholds(seconds: float | None, expected: Freshness) -> None:
    assert classify(seconds, FreshnessThresholds()) == expected


def test_classify_custom_thresholds() -> None:
    custom = FreshnessThresholds(fresh_below=10, recent_below=20, stale_below=30)
    levels = [classify(value, custom) for value in (9, 10, 20, 30)]
    assert levels == [Freshness.FRESH, Freshness.RECENT, Freshness.STALE, Freshness.DORMANT]


@pytest.mark.parametrize(
    ("fresh", "recent", "stale", "ordered"),
    [
        (300, 3_600, DAY, True),
        (1, 1, 1, True),
        (0, 10, 20, False),
        (20, 10, 30, False),
        (10, 30, 20, False),
    ],
)
def test_thresholds_ordering(fresh: int, recent: int, stale: int, ordered: bool) -> None:
    assert FreshnessThresholds(fresh, recent, stale).is_ordered() is ordered


@pytest.mark.parametrize(
    ("offset", "label"),
    [
        (None, "UTC"),
        (timedelta(0), "UTC"),
        (timedelta(hours=3), "UTC+03:00"),
        (timedelta(hours=5, minutes=30), "UTC+05:30"),
        (timedelta(hours=-3), "UTC-03:00"),
        (timedelta(hours=-9, minutes=-30), "UTC-09:30"),
    ],
)
def test_zone_label(offset: timedelta | None, label: str) -> None:
    assert zone_label(offset) == label


def test_format_exact_in_a_given_zone() -> None:
    moment = datetime(2026, 10, 31, 17, 42, 10, tzinfo=UTC)
    assert format_exact(moment, timezone(timedelta(hours=3))) == "2026-10-31 20:42:10 UTC+03:00"
    assert format_exact(moment, UTC) == "2026-10-31 17:42:10 UTC"


def test_format_exact_reads_naive_as_utc() -> None:
    naive = datetime(2026, 1, 2, 3, 4, 5)  # noqa: DTZ001 - the point of the test
    assert format_exact(naive, UTC) == "2026-01-02 03:04:05 UTC"


def test_format_exact_without_zone_uses_the_local_one() -> None:
    moment = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    text = format_exact(moment)
    local = moment.astimezone()
    assert text == f"{local:%Y-%m-%d %H:%M:%S} {zone_label(local.utcoffset())}"


@pytest.mark.parametrize(
    ("number", "english"),
    [
        (0, "0"),
        (999, "999"),
        (1_000, "1,000"),
        (1_234_567, "1,234,567"),
        (-1_234, "-1,234"),
        (100_000, "100,000"),
    ],
)
def test_format_count(number: int, english: str) -> None:
    assert format_count(number, "en") == english
    assert format_count(number, "ru") == english.replace(",", NBSP)


@pytest.mark.parametrize(
    ("size", "english"),
    [
        (-5, "0 B"),
        (0, "0 B"),
        (512, "512 B"),
        (1_023, "1023 B"),
        (1_024, "1.0 KB"),
        (1_536, "1.5 KB"),
        (10 * 1_024, "10 KB"),
        (5 * 1_024**2, "5.0 MB"),
        (12 * 1_024**3, "12 GB"),
        (3 * 1_024**4, "3.0 TB"),
        (5_000 * 1_024**4, "5000 TB"),
    ],
)
def test_format_bytes(size: float, english: str) -> None:
    assert format_bytes(size, "en") == english


def test_format_bytes_russian_unit_and_decimal_comma() -> None:
    assert format_bytes(1_536, "ru") == f"1,5 {ru('bytes.kb')}"
    assert format_bytes(512, "ru") == f"512 {ru('bytes.b')}"


@pytest.mark.parametrize(
    ("fraction", "english"),
    [(-1, "0%"), (0, "0%"), (0.456, "46%"), (1, "100%"), (7, "100%")],
)
def test_format_percent(fraction: float, english: str) -> None:
    assert format_percent(fraction, "en") == english
    assert format_percent(fraction, "ru") == english.replace("%", f"{NBSP}%")


def test_count_phrase_groups_the_count_and_picks_the_plural_form() -> None:
    assert count_phrase(1, "count.chats", "en") == "1 chat"
    assert count_phrase(1_200, "count.chats", "en") == "1,200 chats"
    assert count_phrase(1_200, "count.chats", "ru").startswith(f"1{NBSP}200 ")
    assert count_phrase(1, "count.chats", "ru") != count_phrase(2, "count.chats", "ru")
    assert count_phrase(5, "count.chats", "ru") != count_phrase(2, "count.chats", "ru")
