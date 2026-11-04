"""Parses the service log into records. Pure: no Qt, no file access.

A record starts with a line `2026-10-31T20:21:13.001Z INFO chatimport.worker: message`; every
following line that does not start that way (a traceback, a wrapped message) is its detail.
The parser tolerates garbage: lines before the first timestamp, odd level words, a missing
fraction or zone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import IntEnum
from functools import cached_property
from typing import TYPE_CHECKING, Final

from chatimport.textnorm import fold

if TYPE_CHECKING:
    from collections.abc import Iterable

HEADER: Final = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T ](?P<clock>\d{2}:\d{2}:\d{2})"
    r"(?:[.,](?P<fraction>\d{1,6}))?(?P<zone>Z|[+-]\d{2}:?\d{2})?"
    r"\s+(?P<level>[A-Za-z]+)\s+(?P<logger>[^\s:]+):\s?(?P<message>.*)$"
)
TRACEBACK_MARKER: Final = "Traceback (most recent call last)"


class Level(IntEnum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


_ALIASES: Final = {"WARN": "WARNING", "FATAL": "CRITICAL", "ERR": "ERROR", "TRACE": "DEBUG"}


def normalize_level(word: str) -> Level:
    """Known words (and a few aliases) map to a level; anything else reads as INFO."""
    name = _ALIASES.get(word.upper(), word.upper())
    return Level[name] if name in Level.__members__ else Level.INFO


def _zone(text: str | None) -> timezone:
    if not text or text == "Z":
        return UTC
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))


def _moment(match: re.Match[str]) -> datetime | None:
    fraction = (match["fraction"] or "0").ljust(6, "0")
    try:
        naive = datetime.fromisoformat(f"{match['date']}T{match['clock']}.{fraction}")
    except ValueError:
        return None
    return naive.replace(tzinfo=_zone(match["zone"])).astimezone(UTC)


@dataclass(frozen=True, eq=False)
class LogRecord:
    time: datetime
    level: Level
    logger: str
    message: str
    detail: str = field(default="")

    @cached_property
    def folded(self) -> str:
        """Lower-cased searchable text: logger, message and detail."""
        return fold(f"{self.logger} {self.message} {self.detail}")

    @cached_property
    def source(self) -> str:
        """The logger minus its package: `chatimport.worker_backfill` -> `worker_backfill`."""
        head, _, tail = self.logger.partition(".")
        return tail or head

    @property
    def has_traceback(self) -> bool:
        return bool(self.detail)

    @property
    def line_count(self) -> int:
        return 1 + (self.detail.count("\n") + 1 if self.detail else 0)

    def header(self) -> str:
        stamp = self.time.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return f"{stamp} {self.level.name} {self.logger}: {self.message}"

    def as_text(self) -> str:
        return f"{self.header()}\n{self.detail}" if self.detail else self.header()


def is_record_start(line: str) -> bool:
    return HEADER.match(line) is not None


def parse_header(line: str) -> LogRecord | None:
    match = HEADER.match(line)
    if match is None:
        return None
    moment = _moment(match)
    if moment is None:
        return None
    return LogRecord(
        moment, normalize_level(match["level"]), match["logger"], match["message"].rstrip()
    )


class LogParser:
    """Feeds on whole lines; the record being built is held back until the next header.

    `flush` releases it (the tailer calls it when the file went quiet), so a traceback that
    arrives in one write is never split.
    """

    def __init__(self) -> None:
        self._head: LogRecord | None = None
        self._detail: list[str] = []
        self.orphans: list[str] = []

    def feed(self, lines: Iterable[str]) -> list[LogRecord]:
        done: list[LogRecord] = []
        for raw in lines:
            line = raw.rstrip("\r\n")
            record = parse_header(line)
            if record is not None:
                finished = self.flush()
                if finished is not None:
                    done.append(finished)
                self._head = record
            elif self._head is not None:
                self._detail.append(line)
            elif line.strip():
                self.orphans.append(line)
        return done

    def flush(self) -> LogRecord | None:
        head, self._head = self._head, None
        detail, self._detail = self._detail, []
        if head is None:
            return None
        text = "\n".join(detail).rstrip()
        if not text:
            return head
        return LogRecord(head.time, head.level, head.logger, head.message, text)


def parse_text(text: str) -> tuple[list[str], list[LogRecord]]:
    """Parse a whole chunk: (leading lines that continue an earlier record, the records)."""
    parser = LogParser()
    records = parser.feed(text.splitlines())
    last = parser.flush()
    if last is not None:
        records.append(last)
    return parser.orphans, records
