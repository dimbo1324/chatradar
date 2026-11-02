from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport.records import record_to_bytes
from chatimport.storage.reader import newest_message_date
from tests.fakes import msg

if TYPE_CHECKING:
    from pathlib import Path

BIG = 70 * 1024


def test_newest_date_of_a_large_part_is_read_from_its_tail(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(
        record_to_bytes(msg(1)) + b"x" * BIG + b"\n" + record_to_bytes(msg(2)) + b"\n  \n"
    )
    assert newest_message_date([path]) == msg(2).date


def test_the_window_doubles_until_a_message_is_found(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(record_to_bytes(msg(1)) + b"x" * BIG + b"\n")
    assert newest_message_date([path]) == msg(1).date


def test_a_part_without_messages_gives_none(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(b"{broken\n")
    empty = tmp_path / "2026-10_002.jsonl"
    empty.write_bytes(b"")
    assert newest_message_date([path, empty]) is None


def test_unreadable_parts_are_skipped_for_an_older_one(tmp_path: Path) -> None:
    older = tmp_path / "2026-09_001.jsonl"
    older.write_bytes(record_to_bytes(msg(1)))
    missing = tmp_path / "2026-10_001.jsonl"
    assert newest_message_date([older, missing]) == msg(1).date


def test_no_parts_gives_none() -> None:
    assert newest_message_date([]) is None
