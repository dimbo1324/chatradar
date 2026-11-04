from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

import pytest

from chatimport.records import (
    DeleteRecord,
    EditRecord,
    MediaInfo,
    MediaSavedRecord,
    MessageRecord,
    record_to_line,
)
from chatimport.storage import state as state_module
from chatimport.storage import writer as writer_module
from chatimport.storage.layout import list_parts
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import load_state, save_state
from chatimport.storage.writer import (
    count_lines,
    iter_part_records,
    iter_records,
    scan_part,
)
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import (
    LINE_SEP,
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


def batch(ids: range | list[int], *, month: int = 10) -> list[MessageRecord]:
    return [msg(i, date=at(2026, month, 1 + (i % 27), i % 24)) for i in ids]


def line_size(record: MessageRecord) -> int:
    return len(record_to_line(record).encode("utf-8")) + 1


def test_write_month_of_nothing_returns_the_state_and_writes_nothing(tmp_path: Path) -> None:
    state = fresh_state()
    assert make_writer(tmp_path).write_month(state, "2026-10", []) is state
    assert list(tmp_path.iterdir()) == []


def test_write_month_sorts_by_id_and_fills_one_part(tmp_path: Path) -> None:
    state = make_writer(tmp_path).write_month(fresh_state(), "2026-10", batch([5, 1, 3, 2, 4]))
    assert message_ids(tmp_path) == [1, 2, 3, 4, 5]
    assert part_names(tmp_path) == ["2026-10_001.jsonl"]
    assert state.last_id == 0
    assert_state_matches_files_ignoring_last_id(tmp_path)


def assert_state_matches_files_ignoring_last_id(folder: Path) -> None:
    state = load_state(folder)
    assert state is not None
    for path in list_parts(folder):
        assert state.chunks[path.stem] == scan_part(path)
    assert set(state.chunks) == {p.stem for p in list_parts(folder)}


def test_write_month_dedupes_by_msg_id(tmp_path: Path) -> None:
    records = [msg(1, text="a"), msg(2, text="b"), msg(1, text="c"), msg(2, text="d")]
    make_writer(tmp_path).write_month(fresh_state(), "2026-10", records)
    assert message_ids(tmp_path) == [1, 2]


def test_write_month_splits_by_threshold_and_never_cuts_a_record(tmp_path: Path) -> None:
    records = batch(range(1, 11))
    size = line_size(records[0])
    state = make_writer(tmp_path, max_bytes=size * 3).write_month(fresh_state(), "2026-10", records)
    counts = [info.records for _, info in sorted(state.chunks.items())]
    assert sum(counts) == 10
    assert all(c >= 1 for c in counts)
    assert message_ids(tmp_path) == list(range(1, 11))
    assert_state_matches_files_ignoring_last_id(tmp_path)


def test_write_month_group_closes_exactly_when_the_threshold_is_reached(tmp_path: Path) -> None:
    records = [msg(i, date=at(2026, 10, 1), text="x") for i in range(1, 7)]
    size = line_size(records[0])
    state = make_writer(tmp_path, max_bytes=size * 2).write_month(fresh_state(), "2026-10", records)
    assert [info.records for _, info in sorted(state.chunks.items())] == [2, 2, 2]
    state = make_writer(tmp_path / "b", max_bytes=size * 2 + 1).write_month(
        fresh_state(), "2026-10", records
    )
    assert [info.records for _, info in sorted(state.chunks.items())] == [3, 3]


def test_write_month_with_a_one_byte_threshold_makes_one_part_per_record(tmp_path: Path) -> None:
    state = make_writer(tmp_path, max_bytes=1).write_month(
        fresh_state(), "2026-10", batch(range(1, 6))
    )
    assert len(state.chunks) == 5
    assert all(info.records == 1 for info in state.chunks.values())


def test_write_month_replaces_existing_parts_and_drops_leftover_ones(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = writer.write_month(fresh_state(), "2026-10", batch(range(1, 6)))
    assert len(list_parts(tmp_path)) == 5
    writer = make_writer(tmp_path)
    state = writer.write_month(state, "2026-10", batch([10, 11]))
    assert part_names(tmp_path) == ["2026-10_001.jsonl"]
    assert message_ids(tmp_path) == [10, 11]
    assert set(state.chunks) == {"2026-10_001"}
    assert_state_matches_files_ignoring_last_id(tmp_path)


def test_write_month_is_idempotent(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=400)
    state = writer.write_month(fresh_state(), "2026-10", batch(range(1, 20)))
    snapshot = {p.name: p.read_bytes() for p in list_parts(tmp_path)}
    state_again = writer.write_month(state, "2026-10", batch(range(1, 20)))
    assert {p.name: p.read_bytes() for p in list_parts(tmp_path)} == snapshot
    assert state_again.chunks == state.chunks


def test_write_month_leaves_other_months_alone(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-09", batch([1, 2], month=9))
    september = (tmp_path / "2026-09_001.jsonl").read_bytes()
    writer.write_month(state, "2026-10", batch([3, 4]))
    assert (tmp_path / "2026-09_001.jsonl").read_bytes() == september


def test_write_month_keeps_last_id_untouched(tmp_path: Path) -> None:
    state = fresh_state()
    state = make_writer(tmp_path).write_month(state, "2026-10", batch([8, 9]))
    assert state.last_id == 0


def test_write_month_refuses_more_than_999_parts_and_writes_nothing(tmp_path: Path) -> None:
    records = [msg(i, date=at(2026, 10, 1), text="") for i in range(1, 1002)]
    with pytest.raises(ValueError, match="999"):
        make_writer(tmp_path, max_bytes=1).write_month(fresh_state(), "2026-10", records)
    assert list(tmp_path.iterdir()) == []


def test_write_month_exactly_999_parts_is_allowed(tmp_path: Path) -> None:
    records = [msg(i, date=at(2026, 10, 1), text="") for i in range(1, 1000)]
    state = make_writer(tmp_path, max_bytes=1).write_month(fresh_state(), "2026-10", records)
    assert len(state.chunks) == 999
    assert part_names(tmp_path)[-1] == "2026-10_999.jsonl"


def test_write_month_failure_midway_keeps_state_json_and_leaves_no_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = writer.write_month(fresh_state(), "2026-10", batch([1, 2]))
    save_state(tmp_path, state)
    state_bytes = (tmp_path / "state.json").read_bytes()

    real = state_module.atomic_write_bytes
    calls = {"n": 0}

    def flaky(path: Path, data: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(writer_module, "atomic_write_bytes", flaky)
    with pytest.raises(OSError, match="disk full"):
        writer.write_month(state, "2026-10", batch([1, 2, 3, 4]))
    monkeypatch.undo()

    assert (tmp_path / "state.json").read_bytes() == state_bytes
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    recover_chat(tmp_path, now=NOW)
    assert_state_matches_files(tmp_path)


def test_write_month_replace_failure_keeps_the_old_part_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-10", batch([1, 2]))
    before = (tmp_path / "2026-10_001.jsonl").read_bytes()

    def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError, match="replace failed"):
        writer.write_month(state, "2026-10", batch([7, 8, 9]))
    monkeypatch.undo()
    assert (tmp_path / "2026-10_001.jsonl").read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_files_are_closed_after_write_and_merge(tmp_path: Path) -> None:
    folder = tmp_path / "chat"
    writer = make_writer(folder, max_bytes=200)
    state = writer.write_month(fresh_state(), "2026-10", batch(range(1, 8)))
    writer.merge_month(state, "2026-10", batch(range(8, 12)))
    shutil.rmtree(folder)
    assert not folder.exists()


def test_merge_into_a_month_without_parts_behaves_like_write_month(tmp_path: Path) -> None:
    state = make_writer(tmp_path).merge_month(fresh_state(), "2026-10", batch([3, 1, 2]))
    assert message_ids(tmp_path) == [1, 2, 3]
    assert "2026-10_001" in state.chunks


def test_merge_of_nothing_new_returns_the_state_and_rewrites_nothing(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-10", batch([1, 2, 3]))
    before = (tmp_path / "2026-10_001.jsonl").read_bytes()
    assert writer.merge_month(state, "2026-10", batch([1, 2])) is state
    assert writer.merge_month(state, "2026-10", []) is state
    assert (tmp_path / "2026-10_001.jsonl").read_bytes() == before


def test_merge_existing_ids_win_over_fresh_copies(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(
        fresh_state(), "2026-10", [msg(1, text="original"), msg(3, text="original")]
    )
    writer.merge_month(state, "2026-10", [msg(1, text="NEW"), msg(2, text="fresh")])
    texts = {r.msg_id: r.text for r in all_records(tmp_path) if isinstance(r, MessageRecord)}
    assert texts == {1: "original", 2: "fresh", 3: "original"}


def test_merge_keeps_edits_deletes_and_media_marks_and_orders_them_after_their_message(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(
        fresh_state(),
        [
            msg(2, date=at(2026, 10, 2)),
            msg(4, date=at(2026, 10, 4)),
        ],
    )
    extras = [
        EditRecord(CHAT_ID, 2, at(2026, 10, 5), NOW, "edited", media=MediaInfo("photo")),
        DeleteRecord(CHAT_ID, (4, 2), NOW),
        MediaSavedRecord(CHAT_ID, 4, "media/4.jpg", at(2026, 10, 6)),
    ]
    state = writer.append(state, extras)
    writer.merge_month(
        state, "2026-10", [msg(1, date=at(2026, 10, 1)), msg(3, date=at(2026, 10, 3))]
    )
    records = all_records(tmp_path)
    assert [(type(r).__name__, getattr(r, "msg_id", None)) for r in records] == [
        ("MessageRecord", 1),
        ("MessageRecord", 2),
        ("EditRecord", 2),
        ("MessageRecord", 3),
        ("MessageRecord", 4),
        ("DeleteRecord", None),
        ("MediaSavedRecord", 4),
    ]
    delete = records[-2]
    assert isinstance(delete, DeleteRecord)
    assert delete.msg_ids == (4, 2)
    edit = records[2]
    assert isinstance(edit, EditRecord)
    assert edit.media == MediaInfo("photo")


def test_merge_with_a_delete_of_an_unknown_old_message_stays_in_order(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(
        fresh_state(), [msg(10, date=at(2026, 10, 2)), DeleteRecord(CHAT_ID, (5,), NOW)]
    )
    writer.merge_month(
        state, "2026-10", [msg(3, date=at(2026, 10, 1)), msg(7, date=at(2026, 10, 1))]
    )
    ids = [(type(r).__name__[0], record_id(r)) for r in all_records(tmp_path)]
    assert ids == [("M", 3), ("D", 5), ("M", 7), ("M", 10)]


def record_id(record: object) -> int:
    if isinstance(record, DeleteRecord):
        return max(record.msg_ids)
    assert isinstance(record, (MessageRecord, EditRecord, MediaSavedRecord))
    return record.msg_id


def test_merge_fresh_duplicates_collapse_to_one(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-10", batch([1]))
    writer.merge_month(state, "2026-10", [msg(2, text="a"), msg(2, text="b")])
    assert message_ids(tmp_path) == [1, 2]


def test_merge_repartitions_by_threshold_and_updates_chunks(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=500)
    state = writer.write_month(fresh_state(), "2026-10", batch(range(1, 6)))
    state = writer.merge_month(state, "2026-10", batch(range(6, 40)))
    assert message_ids(tmp_path) == list(range(1, 40))
    assert_state_matches_files_ignoring_last_id(tmp_path)
    assert len(state.chunks) > 1


def test_merge_removes_parts_that_are_no_longer_needed(tmp_path: Path) -> None:
    tiny = make_writer(tmp_path, max_bytes=1)
    state = tiny.write_month(fresh_state(), "2026-10", batch(range(1, 6)))
    roomy = make_writer(tmp_path, max_bytes=10**9)
    state = roomy.merge_month(state, "2026-10", batch([6]))
    assert part_names(tmp_path) == ["2026-10_001.jsonl"]
    assert set(state.chunks) == {"2026-10_001"}
    assert message_ids(tmp_path) == [1, 2, 3, 4, 5, 6]


def test_merge_does_not_touch_other_months(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-09", batch([1], month=9))
    state = writer.write_month(state, "2026-10", batch([2]))
    september = (tmp_path / "2026-09_001.jsonl").read_bytes()
    writer.merge_month(state, "2026-10", batch([3]))
    assert (tmp_path / "2026-09_001.jsonl").read_bytes() == september


def test_merge_survives_a_cut_last_line_in_an_existing_part(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-10", batch([1, 2]))
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(path.read_bytes() + b'{"v":1,"kind":"mess')
    writer.merge_month(state, "2026-10", batch([3]))
    assert message_ids(tmp_path) == [1, 2, 3]
    assert b"mess" not in path.read_bytes().split(b"\n")[-2][-8:]


def test_iter_part_records_skips_garbage_blank_lines_and_a_trailing_partial_line(
    tmp_path: Path,
) -> None:
    good = [record_to_line(msg(i)).encode() for i in (1, 2, 3)]
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(
        good[0]
        + b"\n\n   \n"
        + b"garbage line\n"
        + good[1]
        + b"\n"
        + b'{"kind":"x"}\n'
        + b"\xff\xfe\n"
        + good[2]
        + b"\n"
        + b'{"v":1,"kind":"mess'
    )
    assert [r.msg_id for r in iter_part_records(path) if isinstance(r, MessageRecord)] == [1, 2, 3]


@pytest.mark.parametrize("junk", [b"null", b"[]", b"123", b'"text"', b"true", b"[1,2]"])
def test_iter_part_records_skips_json_lines_that_are_not_objects(
    tmp_path: Path, junk: bytes
) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(record_to_line(msg(1)).encode() + b"\n" + junk + b"\n")
    assert [r.msg_id for r in iter_part_records(path) if isinstance(r, MessageRecord)] == [1]


def test_iter_part_records_reads_crlf_files(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    lines = [record_to_line(msg(i)) for i in (1, 2, 3)]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode())
    assert len(list(iter_part_records(path))) == 3
    assert count_lines(path) == 3


def test_iter_part_records_does_not_split_on_unicode_line_separators(tmp_path: Path) -> None:
    record = msg(1, text=f"a{LINE_SEP}b{chr(0x85)}c{chr(0xB)}d{chr(0xC)}e{chr(0x1C)}f")
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(record_to_line(record).encode() + b"\n")
    (only,) = iter_part_records(path)
    assert isinstance(only, MessageRecord)
    assert only.text == record.text


def test_iter_part_records_of_an_empty_file_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(b"")
    assert list(iter_part_records(path)) == []
    assert count_lines(path) == 0


def test_iter_part_records_of_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(iter_part_records(tmp_path / "2026-10_001.jsonl"))


def test_iter_records_walks_parts_in_name_order_and_accepts_an_explicit_list(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path)
    state = writer.write_month(fresh_state(), "2026-10", batch([5]))
    writer.write_month(state, "2026-09", batch([1], month=9))
    assert [r.msg_id for r in iter_records(tmp_path) if isinstance(r, MessageRecord)] == [1, 5]
    only_october = [tmp_path / "2026-10_001.jsonl"]
    assert [
        r.msg_id for r in iter_records(tmp_path, only_october) if isinstance(r, MessageRecord)
    ] == [5]
    assert list(iter_records(tmp_path / "missing")) == []


def test_scan_part_counts_records_and_ids_from_the_file(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    lines = [
        record_to_line(msg(9)),
        "garbage",
        record_to_line(msg(4)),
        record_to_line(EditRecord(CHAT_ID, 100, at(2026, 10, 1), NOW)),
    ]
    path.write_bytes(("\n".join(lines) + "\n").encode())
    info = scan_part(path)
    assert (info.records, info.first_id, info.last_id) == (3, 4, 9)
    assert info.bytes == path.stat().st_size


def test_scan_part_of_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(b"")
    info = scan_part(path)
    assert (info.records, info.first_id, info.last_id, info.bytes) == (0, 0, 0, 0)
