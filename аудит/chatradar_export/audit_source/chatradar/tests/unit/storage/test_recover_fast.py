from __future__ import annotations

from pathlib import Path

import pytest

from chatimport.records import record_to_bytes
from chatimport.storage import recover as recover_module
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import ChunkInfo, StateUnreadable, save_state
from tests.fakes import NOW, msg
from tests.unit.storage.helpers import (
    assert_state_matches_files,
    at,
    fresh_state,
    make_writer,
    message_ids,
)


def build(folder: Path, months: int = 3) -> None:
    writer = make_writer(folder)
    state = fresh_state()
    for month in range(1, months + 1):
        state = writer.append(state, [msg(month * 10 + i, date=at(2026, month, 5)) for i in (1, 2)])


def count_scans(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    scanned: list[str] = []
    real = recover_module.scan_part

    def counting(path: Path) -> ChunkInfo:
        scanned.append(path.name)
        return real(path)

    monkeypatch.setattr(recover_module, "scan_part", counting)
    return scanned


def test_recover_trusts_state_when_sizes_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(tmp_path)
    scanned = count_scans(monkeypatch)
    recover_chat(tmp_path, now=NOW)
    assert scanned == []

    with (tmp_path / "2026-02_001.jsonl").open("ab") as handle:
        handle.write(record_to_bytes(msg(99, date=at(2026, 2, 6))))
    recover_chat(tmp_path, now=NOW)
    assert scanned == ["2026-02_001.jsonl"]
    assert_state_matches_files(tmp_path)


def test_repair_tail_appends_newline_without_rewrite(tmp_path: Path) -> None:
    part = tmp_path / "2026-10_001.jsonl"
    body = record_to_bytes(msg(1)) + record_to_bytes(msg(2))[:-1]
    part.write_bytes(body)
    recover_chat(tmp_path, now=NOW, fallback_chat_id=1)
    assert part.read_bytes() == body + b"\n"


def test_repair_tail_reads_back_far_enough_for_a_long_last_line(tmp_path: Path) -> None:
    part = tmp_path / "2026-10_001.jsonl"
    long_line = record_to_bytes(msg(2, text="y" * 200_000))
    part.write_bytes(record_to_bytes(msg(1)) + long_line[:-50])
    recover_chat(tmp_path, now=NOW, fallback_chat_id=1)
    assert part.read_bytes() == record_to_bytes(msg(1))


def test_a_single_long_cut_line_is_cut_to_an_empty_part(tmp_path: Path) -> None:
    part = tmp_path / "2026-10_001.jsonl"
    part.write_bytes(record_to_bytes(msg(2, text="z" * 200_000))[:-50])
    recover_chat(tmp_path, now=NOW, fallback_chat_id=1)
    assert part.read_bytes() == b""


def test_repair_tail_keeps_valid_json_of_unknown_kind(tmp_path: Path) -> None:
    part = tmp_path / "2026-10_001.jsonl"
    unknown = b'{"v":1,"kind":"reaction","msg_id":2}'
    part.write_bytes(record_to_bytes(msg(1)) + unknown)
    recover_chat(tmp_path, now=NOW, fallback_chat_id=1)
    assert part.read_bytes() == record_to_bytes(msg(1)) + unknown + b"\n"
    assert message_ids(tmp_path) == [1]


def test_unreadable_state_changes_nothing_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(tmp_path, months=1)
    (tmp_path / ".stale.tmp").write_bytes(b"x")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    real = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self.name == "state.json":
            raise PermissionError("busy")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    with pytest.raises(StateUnreadable):
        recover_chat(tmp_path, now=NOW)
    monkeypatch.undo()
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_a_part_unknown_to_the_state_is_scanned(tmp_path: Path) -> None:
    build(tmp_path, months=1)
    save_state(tmp_path, fresh_state())
    recovered = recover_chat(tmp_path, now=NOW)
    assert recovered.chunks["2026-01_001"].records == 2
