from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.records import DeleteRecord, EditRecord, MessageRecord, Record
from chatimport.storage import month_commit
from chatimport.storage import writer as writer_module
from chatimport.storage.month_commit import (
    commit_month,
    journal_path,
    replay_commits,
    replay_month,
    staged_path,
)
from chatimport.storage.recover import recover_chat
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import (
    all_records,
    assert_state_matches_files,
    at,
    fresh_state,
    make_writer,
    message_ids,
    part_names,
)

if TYPE_CHECKING:
    from pathlib import Path

MONTH = "2026-10"


def october(msg_id: int) -> MessageRecord:
    return msg(msg_id, date=at(2026, 10, 1 + msg_id % 28, msg_id % 24), text="x" * 40)


def build_month(folder: Path) -> tuple[list[Record], Any]:
    """Messages 100..139 plus an edit and a delete, about 25 parts of 600 bytes."""
    writer = make_writer(folder, max_bytes=600)
    state = writer.write_month(fresh_state(), MONTH, [october(i) for i in range(100, 140)])
    extra: list[Record] = [
        EditRecord(CHAT_ID, 101, at(2026, 10, 20), NOW, "edited"),
        DeleteRecord(CHAT_ID, (102,), at(2026, 10, 21)),
    ]
    state = writer.append(state, extra)
    return all_records(folder), state


def kinds_and_ids(records: list[Record]) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for record in records:
        if isinstance(record, DeleteRecord):
            out.update(("delete", i) for i in record.msg_ids)
        else:
            out.add((record.kind, record.msg_id))
    return out


@pytest.mark.parametrize("fail_at", [2, 5, 20])
def test_merge_month_crash_while_staging_keeps_every_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    before, state = build_month(tmp_path)
    assert len(part_names(tmp_path)) > 20
    real = writer_module.atomic_write_bytes
    calls = 0

    def crash(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("killed")
        real(path, data)

    monkeypatch.setattr(writer_module, "atomic_write_bytes", crash)
    with pytest.raises(OSError, match="killed"):
        make_writer(tmp_path, max_bytes=600).merge_month(state, MONTH, [october(50)])
    monkeypatch.undo()

    recover_chat(tmp_path, now=NOW)
    assert kinds_and_ids(all_records(tmp_path)) == kinds_and_ids(before)
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert_state_matches_files(tmp_path)


@pytest.mark.parametrize("fail_at", [1, 2, 10])
def test_merge_month_crash_between_part_replaces_is_finished_by_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_at: int
) -> None:
    before, state = build_month(tmp_path)
    real = month_commit.replace_file
    calls = 0

    def crash(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("power cut")
        real(source, target)

    monkeypatch.setattr(month_commit, "replace_file", crash)
    with pytest.raises(OSError, match="power cut"):
        make_writer(tmp_path, max_bytes=600).merge_month(state, MONTH, [october(50)])
    monkeypatch.undo()
    assert journal_path(tmp_path, MONTH).exists()

    recover_chat(tmp_path, now=NOW)
    after = all_records(tmp_path)
    assert kinds_and_ids(after) == kinds_and_ids(before) | {("message", 50)}
    ids = message_ids(tmp_path)
    assert ids == sorted(set(ids))
    assert not journal_path(tmp_path, MONTH).exists()
    assert_state_matches_files(tmp_path)


def test_a_new_rewrite_first_finishes_an_interrupted_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before, state = build_month(tmp_path)
    real = month_commit.replace_file
    calls = 0

    def crash(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("locked")
        real(source, target)

    monkeypatch.setattr(month_commit, "replace_file", crash)
    writer = make_writer(tmp_path, max_bytes=600)
    with pytest.raises(OSError, match="locked"):
        writer.merge_month(state, MONTH, [october(50)])
    monkeypatch.undo()

    writer.merge_month(state, MONTH, [october(51)])
    expected = kinds_and_ids(before) | {("message", 50), ("message", 51)}
    assert kinds_and_ids(all_records(tmp_path)) == expected


def test_single_part_rewrite_skips_the_journal(tmp_path: Path) -> None:
    written: list[str] = []

    def write(path: Path, data: bytes) -> None:
        written.append(path.name)
        path.write_bytes(data)

    commit_month(tmp_path, MONTH, [b"a\n"], write)
    assert written == [f"{MONTH}_001.jsonl"]
    commit_month(tmp_path, MONTH, [b"a\n", b"b\n"], write)
    assert written[1:] == [
        f".{MONTH}_001.jsonl.new",
        f".{MONTH}_002.jsonl.new",
        f".{MONTH}.commit.json",
    ]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        f"{MONTH}_001.jsonl",
        f"{MONTH}_002.jsonl",
    ]


def plain_write(path: Path, data: bytes) -> None:
    path.write_bytes(data)


def test_a_shrinking_month_deletes_the_surplus_parts(tmp_path: Path) -> None:
    for number in (1, 2, 3):
        (tmp_path / f"{MONTH}_00{number}.jsonl").write_bytes(b"old\n")
    commit_month(tmp_path, MONTH, [b"new\n"], plain_write)
    commit_month(tmp_path, MONTH, [b"one\n", b"two\n"], plain_write)
    assert part_names(tmp_path) == [f"{MONTH}_001.jsonl", f"{MONTH}_002.jsonl"]


def test_staged_parts_without_a_journal_are_dropped_and_old_parts_kept(tmp_path: Path) -> None:
    (tmp_path / f"{MONTH}_001.jsonl").write_bytes(b"old\n")
    staged_path(tmp_path, MONTH, 1).write_bytes(b"new\n")
    assert replay_commits(tmp_path) == []
    assert (tmp_path / f"{MONTH}_001.jsonl").read_bytes() == b"old\n"
    assert not staged_path(tmp_path, MONTH, 1).exists()


@pytest.mark.parametrize(
    "content",
    [b"{", b"[]", b'{"month": "2026-13", "parts": 1}', b'{"month": "2026-10", "parts": 0}'],
)
def test_a_broken_journal_is_dropped_without_touching_parts(tmp_path: Path, content: bytes) -> None:
    (tmp_path / f"{MONTH}_001.jsonl").write_bytes(b"old\n")
    staged_path(tmp_path, MONTH, 1).write_bytes(b"new\n")
    journal_path(tmp_path, MONTH).write_bytes(content)
    replay_month(tmp_path, MONTH)
    assert journal_path(tmp_path, MONTH).exists()
    assert replay_commits(tmp_path) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{MONTH}_001.jsonl"]
    assert (tmp_path / f"{MONTH}_001.jsonl").read_bytes() == b"old\n"


def test_replaying_a_journal_twice_is_harmless(tmp_path: Path) -> None:
    (tmp_path / f"{MONTH}_002.jsonl").write_bytes(b"surplus\n")
    staged_path(tmp_path, MONTH, 1).write_bytes(b"new\n")
    journal_path(tmp_path, MONTH).write_bytes(json.dumps({"month": MONTH, "parts": 1}).encode())
    assert replay_commits(tmp_path) == [MONTH]
    assert replay_commits(tmp_path) == []
    replay_month(tmp_path, MONTH)
    assert part_names(tmp_path) == [f"{MONTH}_001.jsonl"]
    assert (tmp_path / f"{MONTH}_001.jsonl").read_bytes() == b"new\n"
