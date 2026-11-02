from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chatimport.gui.models.log_parser import (
    Level,
    LogParser,
    LogRecord,
    is_record_start,
    normalize_level,
    parse_header,
    parse_text,
)

STAMP = "2026-10-31T20:21:13.001Z"
TRACEBACK = (
    'Traceback (most recent call last):\n  File "x.py", line 1, in <module>\nValueError: boom'
)


@pytest.mark.parametrize(
    ("word", "level"),
    [
        ("DEBUG", Level.DEBUG),
        ("info", Level.INFO),
        ("Warning", Level.WARNING),
        ("WARN", Level.WARNING),
        ("ERROR", Level.ERROR),
        ("err", Level.ERROR),
        ("FATAL", Level.CRITICAL),
        ("CRITICAL", Level.CRITICAL),
        ("TRACE", Level.DEBUG),
        ("NOTICE", Level.INFO),
        ("", Level.INFO),
    ],
)
def test_normalize_level(word: str, level: Level) -> None:
    assert normalize_level(word) is level


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            f"{STAMP} INFO chatimport.worker: hello",
            datetime(2026, 10, 31, 20, 21, 13, 1000, tzinfo=UTC),
        ),
        (
            "2026-10-31 20:21:13 INFO app: no fraction no zone",
            datetime(2026, 10, 31, 20, 21, 13, tzinfo=UTC),
        ),
        (
            "2026-10-31 20:21:13,5 INFO app: comma fraction",
            datetime(2026, 10, 31, 20, 21, 13, 500_000, tzinfo=UTC),
        ),
        (
            "2026-10-31T20:21:13+03:00 INFO app: plus zone",
            datetime(2026, 10, 31, 17, 21, 13, tzinfo=UTC),
        ),
        (
            "2026-10-31T20:21:13-0530 INFO app: minus zone",
            datetime(2026, 11, 1, 1, 51, 13, tzinfo=UTC),
        ),
    ],
)
def test_parse_header_moments(line: str, expected: datetime) -> None:
    record = parse_header(line)
    assert record is not None
    assert record.time == expected
    assert record.time.tzinfo is UTC


def test_parse_header_fields() -> None:
    record = parse_header(f"{STAMP} WARNING chatimport.worker_backfill: slow   ")
    assert record is not None
    assert record.level is Level.WARNING
    assert record.logger == "chatimport.worker_backfill"
    assert record.message == "slow"
    assert record.source == "worker_backfill"
    assert record.detail == ""


@pytest.mark.parametrize(
    "line",
    [
        "",
        "garbage",
        '  File "x.py", line 1',
        "2026-10-31T20:21:13Z INFO",
        "2026-13-45T25:61:61Z INFO app: impossible date",
    ],
)
def test_parse_header_rejects_non_headers(line: str) -> None:
    assert parse_header(line) is None


def test_is_record_start() -> None:
    assert is_record_start(f"{STAMP} INFO a: b")
    assert not is_record_start("Traceback (most recent call last):")
    assert is_record_start("2026-13-45T25:61:61Z INFO app: matches shape only")


def test_record_properties() -> None:
    plain = LogRecord(datetime(2026, 1, 2, 3, 4, 5, 6000, tzinfo=UTC), Level.ERROR, "app", "Msg")
    assert plain.source == "app"
    assert not plain.has_traceback
    assert plain.line_count == 1
    assert plain.header() == "2026-01-02T03:04:05.006Z ERROR app: Msg"
    assert plain.as_text() == plain.header()
    assert plain.folded == "app msg"
    detailed = LogRecord(plain.time, Level.ERROR, "chatimport.x", "Msg", TRACEBACK)
    assert detailed.has_traceback
    assert detailed.line_count == 4
    assert detailed.source == "x"
    assert detailed.as_text() == f"{detailed.header()}\n{TRACEBACK}"
    assert "valueerror" in detailed.folded


def test_parser_groups_traceback_into_detail() -> None:
    lines = [
        "stray line before any header",
        "",
        f"{STAMP} INFO chatimport.a: first",
        f"{STAMP} ERROR chatimport.b: failed",
        *TRACEBACK.splitlines(),
        "",
        f"{STAMP} INFO chatimport.c: last\r\n",
    ]
    parser = LogParser()
    done = parser.feed(lines)
    assert [record.message for record in done] == ["first", "failed"]
    assert done[1].detail == TRACEBACK
    assert parser.orphans == ["stray line before any header"]
    last = parser.flush()
    assert last is not None
    assert last.message == "last"
    assert parser.flush() is None


def test_parser_holds_back_the_last_record_until_flush() -> None:
    parser = LogParser()
    assert parser.feed([f"{STAMP} INFO a: one"]) == []
    assert parser.feed(["   wrapped continuation"]) == []
    flushed = parser.flush()
    assert flushed is not None
    assert flushed.detail == "   wrapped continuation"


def test_parse_text_returns_orphans_and_records() -> None:
    text = f"tail of an earlier record\n{STAMP} INFO a: one\n{STAMP} INFO a: two\n  more\n"
    orphans, records = parse_text(text)
    assert orphans == ["tail of an earlier record"]
    assert [record.message for record in records] == ["one", "two"]
    assert records[1].detail == "  more"
    assert parse_text("") == ([], [])
    assert parse_text("only garbage\n") == (["only garbage"], [])
