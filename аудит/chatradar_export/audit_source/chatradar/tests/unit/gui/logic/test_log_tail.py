from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.gui.models import log_tail
from chatimport.gui.models.log_tail import (
    LogTail,
    OlderBatch,
    PollResult,
    _complete_end,  # pyright: ignore[reportPrivateUsage]
    _signature,  # pyright: ignore[reportPrivateUsage]
    read_back,
)

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.gui.models.log_parser import LogRecord

NAME = "chatimport.log"


def line(n: int, text: str = "") -> str:
    return f"2026-10-31T20:{n // 60:02d}:{n % 60:02d}.000Z INFO t.x: msg{n}{text}\n"


def lines(numbers: range) -> str:
    return "".join(line(n) for n in numbers)


def messages(records: list[LogRecord]) -> list[str]:
    return [record.message for record in records]


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def append(path: Path, text: str) -> None:
    with path.open("ab") as handle:
        handle.write(text.encode("utf-8"))


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / NAME


def test_signature_variants(tmp_path: Path) -> None:
    path = tmp_path / "s.txt"
    cases = [
        (b"first\nsecond", b"first\n"),
        (b"no newline", None),
        (b"x" * 300, b"x" * 256),
        (b"", None),
    ]
    for data, expected in cases:
        path.write_bytes(data)
        with path.open("rb") as handle:
            assert _signature(handle) == expected


def test_complete_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "e.txt"
    path.write_bytes(b"abc")
    assert _complete_end(path) == 0
    path.write_bytes(b"abc\ndef")
    assert _complete_end(path) == 4
    path.write_bytes(b"")
    assert _complete_end(path) == 0
    monkeypatch.setattr(log_tail, "CHUNK_BYTES", 8)
    path.write_bytes(b"0123456789\nabc")
    assert _complete_end(path) == 11
    path.write_bytes(b"0123456789abcdefghij")
    assert _complete_end(path) == 0


def test_read_back_returns_everything_for_a_small_file(log: Path) -> None:
    write(log, lines(range(5)))
    records, start = read_back(log, log.stat().st_size, 100)
    assert messages(records) == [f"msg{n}" for n in range(5)]
    assert start == 0


def test_read_back_stops_after_enough_records_and_reports_the_offset(
    log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_tail, "CHUNK_BYTES", 200)
    write(log, lines(range(40)))
    size = log.stat().st_size
    records, start = read_back(log, size, 3)
    assert len(records) > 3
    assert messages(records)[-1] == "msg39"
    assert 0 < start < size
    with log.open("rb") as handle:
        handle.seek(start)
        assert handle.read(4) == b"2026"
    older, older_start = read_back(log, start, 3)
    assert messages(older)[-1] == f"msg{40 - len(records) - 1}"
    assert older_start < start


def test_read_back_skips_a_partial_first_line(log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(log_tail, "CHUNK_BYTES", 50)
    write(log, lines(range(10)))
    records, start = read_back(log, log.stat().st_size, 1)
    assert messages(records)[0].startswith("msg")
    assert start > 0


def test_read_back_with_no_newline_in_the_window_finds_nothing(
    log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_tail, "CHUNK_BYTES", 16)
    monkeypatch.setattr(log_tail, "MAX_BACK_BYTES", 16)
    write(log, "x" * 100 + "\n" + line(1))
    assert read_back(log, log.stat().st_size, 5) == ([], 0)


def test_read_back_respects_the_back_limit(log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(log_tail, "CHUNK_BYTES", 100)
    monkeypatch.setattr(log_tail, "MAX_BACK_BYTES", 250)
    write(log, lines(range(30)))
    records, start = read_back(log, log.stat().st_size, 1_000)
    assert 0 < len(records) < 30
    assert start > 0


def test_read_back_of_garbage_is_empty(log: Path) -> None:
    write(log, "not a log\nat all\n")
    assert read_back(log, log.stat().st_size, 5) == ([], 0)


def test_read_back_keeps_a_traceback_with_its_record(log: Path) -> None:
    write(log, line(1) + line(2) + "Traceback (most recent call last):\n  boom\n")
    records, _ = read_back(log, log.stat().st_size, 10)
    assert records[-1].detail == "Traceback (most recent call last):\n  boom"


def test_read_back_replaces_invalid_utf8(log: Path) -> None:
    log.write_bytes(line(1).encode().replace(b"msg1", b"m\xff\xfeg"))
    records, _ = read_back(log, log.stat().st_size, 5)
    assert "�" in records[0].message


def test_load_tail_missing_and_empty_files(log: Path) -> None:
    tail = LogTail(log.parent)
    assert tail.path == log
    assert tail.load_tail(10) == []
    assert tail.has_older
    log.write_bytes(b"")
    assert tail.load_tail(10) == []
    assert tail.poll().exists


def test_load_tail_whole_file_marks_the_rest_as_older(log: Path) -> None:
    write(log, lines(range(5)))
    tail = LogTail(log.parent, backups=2)
    assert messages(tail.load_tail(100)) == [f"msg{n}" for n in range(5)]
    assert tail.has_older
    batch = tail.load_older(10)
    assert batch == OlderBatch([], True)
    assert not tail.has_older


def test_load_older_walks_backwards_through_rotated_files(
    log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_tail, "CHUNK_BYTES", 200)
    write(log.with_name(NAME + ".2"), lines(range(0, 10)))
    write(log.with_name(NAME + ".1"), lines(range(10, 20)))
    write(log, lines(range(20, 60)))
    tail = LogTail(log.parent, backups=3)
    current = tail.load_tail(5)
    assert messages(current)[-1] == "msg59"
    gathered: list[str] = []
    exhausted = False
    for _ in range(50):
        batch = tail.load_older(5)
        gathered = messages(batch.records) + gathered
        exhausted = batch.exhausted
        if exhausted:
            break
    assert exhausted
    everything = gathered + messages(current)
    assert everything == [f"msg{n}" for n in range(60)]
    assert tail.load_older(5) == OlderBatch([], True)


def test_load_older_skips_missing_backups(log: Path) -> None:
    write(log, lines(range(3)))
    write(log.with_name(NAME + ".2"), lines(range(10, 13)))
    tail = LogTail(log.parent, backups=3)
    tail.load_tail(100)
    batch = tail.load_older(100)
    assert messages(batch.records) == ["msg10", "msg11", "msg12"]
    assert batch.exhausted


def test_forget_older_stops_further_loading(log: Path) -> None:
    write(log, lines(range(3)))
    tail = LogTail(log.parent, backups=3)
    tail.load_tail(100)
    tail.forget_older()
    assert not tail.has_older
    assert tail.load_older(10) == OlderBatch([], True)


def test_poll_before_any_load_on_a_missing_file(log: Path) -> None:
    result = LogTail(log.parent).poll()
    assert not result.exists
    assert result.records == []


def test_poll_appends_whole_lines_and_waits_for_the_partial_one(log: Path) -> None:
    write(log, lines(range(2)))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    assert tail.poll() == PollResult()
    append(log, line(2)[:30])
    assert tail.poll().records == []
    append(log, line(2)[30:] + line(3))
    result = tail.poll()
    assert messages(result.records) == ["msg2", "msg3"]
    assert not result.rotated
    assert not result.more


def test_poll_holds_a_record_until_the_file_goes_quiet(log: Path) -> None:
    write(log, line(0))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    append(log, line(1) + "Traceback (most recent call last):\n")
    first = tail.poll()
    assert messages(first.records) == ["msg1"]
    assert first.records[0].detail.startswith("Traceback")


def test_poll_after_an_empty_file_learns_the_signature(log: Path) -> None:
    log.write_bytes(b"")
    tail = LogTail(log.parent)
    tail.load_tail(10)
    append(log, "no newline yet")
    assert tail.poll().records == []
    write(log, lines(range(2)))
    assert messages(tail.poll().records) == ["msg0", "msg1"]


def test_poll_reads_in_slices_when_a_lot_arrived(
    log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_tail, "MAX_POLL_BYTES", 200)
    write(log, line(0))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    append(log, lines(range(1, 30)))
    seen: list[str] = []
    for _ in range(100):
        result = tail.poll()
        seen += messages(result.records)
        if not result.more:
            break
    assert seen == [f"msg{n}" for n in range(1, 30)]


def test_poll_notices_truncation(log: Path) -> None:
    write(log, lines(range(5)))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    write(log, line(0))
    result = tail.poll()
    assert result.rotated
    assert messages(result.records) == ["msg0"]


def test_poll_notices_rotation_and_drains_the_old_file(log: Path) -> None:
    write(log, lines(range(3)))
    tail = LogTail(log.parent, backups=2)
    tail.load_tail(10)
    old = lines(range(3)) + lines(range(3, 5))
    log.replace(log.with_name(NAME + ".1"))
    write(log.with_name(NAME + ".1"), old)
    write(log, line(100) + line(101))
    result = tail.poll()
    assert result.rotated
    assert messages(result.records) == ["msg3", "msg4", "msg100", "msg101"]


def test_rotation_with_the_old_file_not_found_still_reads_the_new_one(log: Path) -> None:
    write(log, lines(range(3)))
    tail = LogTail(log.parent, backups=2)
    tail.load_tail(10)
    write(log, line(200))
    result = tail.poll()
    assert result.rotated
    assert messages(result.records) == ["msg200"]


def test_rotation_skips_backups_with_another_signature(log: Path) -> None:
    write(log, lines(range(3)))
    tail = LogTail(log.parent, backups=3)
    tail.load_tail(10)
    write(log.with_name(NAME + ".1"), line(500))
    write(log.with_name(NAME + ".2"), lines(range(3)) + line(3))
    write(log, line(300))
    result = tail.poll()
    assert messages(result.records) == ["msg3", "msg300"]


def test_rotation_drain_without_new_complete_lines(log: Path) -> None:
    write(log, lines(range(3)))
    tail = LogTail(log.parent, backups=2)
    tail.load_tail(10)
    write(log.with_name(NAME + ".1"), lines(range(3)))
    write(log, line(400))
    assert messages(tail.poll().records) == ["msg400"]


def test_rotation_with_an_unknown_old_signature_skips_the_drain(log: Path) -> None:
    log.write_bytes(b"")
    tail = LogTail(log.parent, backups=2)
    tail.load_tail(10)
    assert tail._signature is None  # pyright: ignore[reportPrivateUsage]
    result = PollResult()
    tail._drain_rotated(result)  # pyright: ignore[reportPrivateUsage]
    assert result.records == []


def test_poll_notices_a_vanished_file_and_its_return(log: Path) -> None:
    write(log, lines(range(2)))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    log.unlink()
    gone = tail.poll()
    assert not gone.exists
    write(log, line(7))
    back = tail.poll()
    assert back.exists
    assert messages(back.records) == ["msg7"]


def test_vanished_file_releases_a_held_record(log: Path) -> None:
    write(log, line(0))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    append(log, line(1) + "  detail\n")
    assert messages(tail.poll().records) == ["msg1"]
    append(log, line(2))
    log.unlink()
    tail._parser.feed([line(5)])  # pyright: ignore[reportPrivateUsage]
    assert messages(tail.poll().records) == ["msg5"]


def test_poll_reports_an_unreadable_path_without_raising(log: Path) -> None:
    log.mkdir()
    tail = LogTail(log.parent)
    result = tail.poll()
    assert result.exists
    assert result.records == []


def test_poll_returns_nothing_while_a_load_holds_the_lock(log: Path) -> None:
    write(log, lines(range(2)))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    append(log, line(2))
    with tail._lock:  # pyright: ignore[reportPrivateUsage]
        assert tail.poll() == PollResult()
    assert messages(tail.poll().records) == ["msg2"]


def test_poll_drops_orphan_lines(log: Path) -> None:
    write(log, line(0))
    tail = LogTail(log.parent)
    tail.load_tail(10)
    tail._parser = type(tail._parser)()  # pyright: ignore[reportPrivateUsage]
    append(log, "orphan\n" + line(1))
    tail.poll()
    assert tail._parser.orphans == []  # pyright: ignore[reportPrivateUsage]
