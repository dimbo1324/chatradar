"""Pure display formatting: ages, freshness, exact moments, sizes and counts.

No Qt and no clock here: every function takes its inputs, so each is table-testable. Words and
separators come from the string catalogue (`time.*`, `bytes.*`, `format.*`), never from this file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from chatimport.gui.strings import translate, translate_plural

if TYPE_CHECKING:
    from chatimport.gui.strings import Language

JUST_NOW_BELOW: Final = 5
DAY: Final = 86_400

_UNITS: Final[tuple[tuple[str, int], ...]] = (
    ("y", 365 * DAY),
    ("mo", 30 * DAY),
    ("wk", 7 * DAY),
    ("d", DAY),
    ("h", 3_600),
    ("min", 60),
    ("s", 1),
)
_BYTE_UNITS: Final = ("b", "kb", "mb", "gb", "tb")


def _split_age(total: int) -> list[tuple[str, int]]:
    for index, (name, size) in enumerate(_UNITS):
        if total < size:
            continue
        head = total // size
        parts = [(name, head)]
        if index + 1 < len(_UNITS):
            next_name, next_size = _UNITS[index + 1]
            # 360-364 days after a year would read "12 mo": cap at the 11 that fit a year.
            tail = min((total - head * size) // next_size, size // next_size - 1)
            if tail > 0:
                parts.append((next_name, tail))
        return parts
    return [("s", 0)]


def humanize_age(seconds: float | None, language: Language) -> str:
    """The two largest units of a duration: `42 s`, `12 min 5 s`, `2 d 4 h`, `1 y 3 mo`.

    Below five seconds the "just now" phrase; `None` and negative values read as unknown.
    """
    if seconds is None or math.isnan(seconds) or seconds < 0:
        return translate(language, "time.unknown")
    total = int(seconds)
    if total < JUST_NOW_BELOW:
        return translate(language, "time.just_now")
    return " ".join(
        f"{value} {translate(language, f'time.{name}')}" for name, value in _split_age(total)
    )


def format_ago(seconds: float | None, language: Language) -> str:
    """`humanize_age` with the "ago" wording; "just now" and "unknown" stay as they are."""
    if seconds is None or math.isnan(seconds) or seconds < JUST_NOW_BELOW:
        return humanize_age(seconds, language)
    return translate(language, "time.ago", age=humanize_age(seconds, language))


class Freshness(StrEnum):
    FRESH = "fresh"
    RECENT = "recent"
    STALE = "stale"
    DORMANT = "dormant"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FreshnessThresholds:
    """Ages in seconds below which a chat counts as fresh, recent and stale; older is dormant."""

    fresh_below: int = 300
    recent_below: int = 3_600
    stale_below: int = DAY

    def is_ordered(self) -> bool:
        return 0 < self.fresh_below <= self.recent_below <= self.stale_below


def classify(seconds: float | None, thresholds: FreshnessThresholds) -> Freshness:
    if seconds is None or math.isnan(seconds) or seconds < 0:
        return Freshness.UNKNOWN
    if seconds < thresholds.fresh_below:
        return Freshness.FRESH
    if seconds < thresholds.recent_below:
        return Freshness.RECENT
    if seconds < thresholds.stale_below:
        return Freshness.STALE
    return Freshness.DORMANT


def zone_label(offset: timedelta | None) -> str:
    if offset is None or offset == timedelta(0):
        return "UTC"
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def format_exact(moment: datetime, tz: tzinfo | None = None) -> str:
    """`2026-10-31 20:42:10 UTC+03:00`: the full instant to the second with its zone.

    A naive datetime is read as UTC; `tz=None` renders in the machine's local zone.
    """
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    local = aware.astimezone(tz) if tz is not None else aware.astimezone()
    return f"{local:%Y-%m-%d %H:%M:%S} {zone_label(local.utcoffset())}"


def _group_digits(text: str, separator: str) -> str:
    groups: list[str] = []
    while len(text) > 3:
        groups.insert(0, text[-3:])
        text = text[:-3]
    groups.insert(0, text)
    return separator.join(groups)


def format_count(n: int, language: Language) -> str:
    """Thousands-grouped integer with the language's separator (a no-break space in Russian)."""
    separator = translate(language, "format.thousands")
    sign = "-" if n < 0 else ""
    return sign + _group_digits(str(abs(n)), separator)


def format_bytes(size: float, language: Language) -> str:
    """`512 B`, `1.5 MB`, `12 GB` with binary steps; one decimal below ten."""
    value = max(float(size), 0.0)
    index = 0
    while value >= 1024 and index < len(_BYTE_UNITS) - 1:
        value /= 1024
        index += 1
    unit = translate(language, f"bytes.{_BYTE_UNITS[index]}")
    if index == 0:
        return f"{int(value)} {unit}"
    decimal = translate(language, "format.decimal")
    number = f"{value:.1f}" if value < 10 else f"{value:.0f}"
    return f"{number.replace('.', decimal)} {unit}"


def format_percent(fraction: float, language: Language) -> str:
    clamped = min(max(fraction, 0.0), 1.0)
    return translate(language, "format.percent", value=round(clamped * 100))


def count_phrase(n: int, key: str, language: Language) -> str:
    """`3 chats` or its Russian form: a plural catalogue entry with the grouped count as `{n}`."""
    return translate_plural(language, n, key, n=format_count(n, language))
