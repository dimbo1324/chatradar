from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.records import MessageRecord, Record, record_to_bytes
from chatimport.storage import writer as writer_module
from chatimport.storage.recover import recover_chat
from chatimport.storage.writer import PartMissing
from tests.fakes import NOW, msg
from tests.unit.storage.helpers import (
    assert_state_matches_files,
    at,
    fresh_state,
    make_writer,
    message_ids,
)

if TYPE_CHECKING:
    from pathlib import Path

UNKNOWN = b'{"v":1,"kind":"reaction","chat_id":1,"msg_id":3,"emoji":"x"}'


def october(msg_id: int) -> MessageRecord:
    return msg(msg_id, date=at(2026, 10, 1 + msg_id % 28))


def test_write_records_encodes_each_record_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    real = writer_module.record_to_bytes

    def counting(record: Record) -> bytes:
        nonlocal calls
        calls += 1
        return real(record)

    monkeypatch.setattr(writer_module, "record_to_bytes", counting)
    make_writer(tmp_path, max_bytes=300).write_month(
        fresh_state(), "2026-10", [october(i) for i in range(1, 41)]
    )
    assert calls == 40
    assert message_ids(tmp_path) == list(range(1, 41))


def test_append_after_the_current_part_was_deleted_by_hand_asks_for_recovery(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [october(1), october(2)])
    (tmp_path / "2026-10_001.jsonl").unlink()

    with pytest.raises(PartMissing, match="2026-10_001"):
        writer.append(state, [october(3)])
    assert not (tmp_path / "2026-10_001.jsonl").exists()

    recovered = recover_chat(tmp_path, now=NOW)
    after = writer.append(recovered, [october(3)])
    assert after.chunks["2026-10_001"].records == 1
    assert_state_matches_files(tmp_path)


def test_merge_month_keeps_lines_it_cannot_read_byte_for_byte(tmp_path: Path) -> None:
    part = tmp_path / "2026-10_001.jsonl"
    original = record_to_bytes(october(2)) + UNKNOWN + b"\n" + record_to_bytes(october(4))
    part.write_bytes(original)
    state = recover_chat(tmp_path, now=NOW)

    make_writer(tmp_path).merge_month(state, "2026-10", [october(1), october(3)])

    data = part.read_bytes()
    assert UNKNOWN + b"\n" in data
    assert data.index(record_to_bytes(october(2))) < data.index(UNKNOWN)
    assert data.index(UNKNOWN) < data.index(record_to_bytes(october(3)))
    assert message_ids(tmp_path) == [1, 2, 3, 4]
    assert_state_matches_files(tmp_path)


def test_merge_month_into_a_part_of_only_unreadable_lines_keeps_them(tmp_path: Path) -> None:
    part = tmp_path / "2026-10_001.jsonl"
    part.write_bytes(UNKNOWN + b"\n")
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=1)
    make_writer(tmp_path).merge_month(state, "2026-10", [october(7)])
    assert part.read_bytes().startswith(UNKNOWN + b"\n")
    assert message_ids(tmp_path) == [7]
