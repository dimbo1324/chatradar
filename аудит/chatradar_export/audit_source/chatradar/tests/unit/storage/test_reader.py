from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.records import EditRecord, MessageRecord, record_to_bytes
from chatimport.storage.reader import (
    decode_line,
    first_message,
    iter_part_records,
    read_appended,
    read_part_lines,
)
from tests.fakes import CHAT_ID, NOW, msg

if TYPE_CHECKING:
    from pathlib import Path

DEEP = b'{"a":' + b"[" * 100_000 + b"]" * 100_000 + b"}"


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (record_to_bytes(msg(1)).strip(), MessageRecord),
        (record_to_bytes(EditRecord(CHAT_ID, 1, NOW, NOW, "t")).strip(), EditRecord),
        (b"{broken", None),
        (b"[]", None),
        (b"\xff\xfe", None),
        (b'{"kind":"reaction","v":1}', None),
        (b'{"kind":"message"}', None),
        (DEEP, None),
        (b"[" * 100_000, None),
    ],
)
def test_decode_line_table(raw: bytes, kind: type | None) -> None:
    record = decode_line(raw)
    if kind is None:
        assert record is None
    else:
        assert isinstance(record, kind)


def test_readers_skip_a_deeply_nested_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(record_to_bytes(msg(1)) + DEEP + b"\n" + record_to_bytes(msg(2)))
    with caplog.at_level("WARNING"):
        ids = [r.msg_id for r in iter_part_records(path) if isinstance(r, MessageRecord)]
    assert ids == [1, 2]
    assert any(getattr(r, "lines", None) == 1 for r in caplog.records)


def test_read_part_lines_keeps_original_bytes_of_every_line(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    unknown = b'{"v":1,"kind":"reaction","msg_id":3}'
    path.write_bytes(record_to_bytes(msg(1)) + b"\n  \n" + unknown + b"\r\n" + b"{cut")
    lines = read_part_lines(path)
    assert [line.data for line in lines] == [
        record_to_bytes(msg(1)),
        unknown + b"\n",
        b"{cut\n",
    ]
    assert [line.record is None for line in lines] == [False, True, True]


def test_read_appended_returns_complete_lines_and_the_next_offset(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    first = record_to_bytes(msg(1))
    path.write_bytes(first)
    records, offset = read_appended(path, 0)
    assert [r.msg_id for r in records if isinstance(r, MessageRecord)] == [1]
    assert offset == len(first)

    second = record_to_bytes(msg(2))
    with path.open("ab") as handle:
        handle.write(second + second[:10])
    records, offset2 = read_appended(path, offset)
    assert [r.msg_id for r in records if isinstance(r, MessageRecord)] == [2]
    assert offset2 == len(first) + len(second)

    with path.open("ab") as handle:
        handle.write(second[10:])
    records, offset3 = read_appended(path, offset2)
    assert [r.msg_id for r in records if isinstance(r, MessageRecord)] == [2]
    assert offset3 == path.stat().st_size


def test_first_message_skips_edits_and_optionally_unreadable_parts(tmp_path: Path) -> None:
    edits = tmp_path / "2026-09_001.jsonl"
    edits.write_bytes(record_to_bytes(EditRecord(CHAT_ID, 9, NOW, NOW)))
    missing = tmp_path / "2026-09_002.jsonl"
    real = tmp_path / "2026-10_001.jsonl"
    real.write_bytes(record_to_bytes(msg(5)) + record_to_bytes(msg(6)))

    found = first_message([edits, missing, real], skip_unreadable=True)
    assert found is not None
    assert found.msg_id == 5
    assert first_message([edits]) is None
    with pytest.raises(FileNotFoundError):
        first_message([edits, missing, real])
