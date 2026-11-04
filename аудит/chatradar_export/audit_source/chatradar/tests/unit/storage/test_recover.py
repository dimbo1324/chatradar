from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from chatimport.records import EditRecord, record_to_line
from chatimport.storage.recover import FLOOR_REASON_MANUAL_DELETE, recover_chat
from chatimport.storage.state import (
    PHASE_LIVE,
    PHASE_RECOVER,
    BackfillState,
    ChunkInfo,
    load_state,
    save_state,
)
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import (
    EMOJI,
    LINE_SEP,
    RU_LOWER,
    assert_state_matches_files,
    at,
    fresh_state,
    make_writer,
    message_ids,
    part_names,
)

if TYPE_CHECKING:
    from pathlib import Path


def line(msg_id: int, month: int = 10) -> bytes:
    return record_to_line(msg(msg_id, date=at(2026, month, 1 + msg_id % 27))).encode()


def write_part(folder: Path, name: str, *lines: bytes, newline: bool = True) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    body = b"\n".join(lines)
    path.write_bytes(body + (b"\n" if newline and lines else b""))
    return path


def test_clean_folder_is_left_byte_identical(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=400)
    state = fresh_state()
    for i in range(1, 15):
        state = writer.append(state, [msg(i, date=at(2026, 10, 1, 0, i))])
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    recovered = recover_chat(tmp_path, now=NOW)
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    parts_before = {k: v for k, v in before.items() if k != "state.json"}
    assert {k: v for k, v in after.items() if k != "state.json"} == parts_before
    assert recovered.last_id == 14
    assert recovered.chunks == state.chunks
    assert load_state(tmp_path) == recovered


@pytest.mark.parametrize(
    "tail",
    [
        b'{"v":1,"kind":"mess',
        b"{",
        b"garbage",
        b"\x00\x00\x00\x00",
        b"\xff\xfe",
        b'{"v":1,"kind":"message","chat_id":1',
    ],
)
def test_cut_last_line_without_newline_is_truncated_to_the_last_newline(
    tmp_path: Path, tail: bytes
) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", line(1), line(2))
    path.write_bytes(path.read_bytes() + tail)
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == line(1) + b"\n" + line(2) + b"\n"
    assert state.last_id == 2
    assert_state_matches_files(tmp_path)


def test_broken_last_line_that_ends_with_a_newline_is_cut_too(tmp_path: Path) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", line(1), b"garbage")
    recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == line(1) + b"\n"


def test_a_part_that_is_only_a_broken_line_becomes_empty(tmp_path: Path) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", b'{"cut', newline=False)
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == b""
    assert state.chunks["2026-10_001"] == ChunkInfo(0, 0, 0, 0)
    assert state.last_id == 0


def test_valid_last_line_missing_its_newline_gets_one(tmp_path: Path) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", line(1), line(2), newline=False)
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == line(1) + b"\n" + line(2) + b"\n"
    assert state.last_id == 2
    assert state.chunks["2026-10_001"].records == 2


def test_the_next_append_after_a_repaired_missing_newline_does_not_glue_lines(
    tmp_path: Path,
) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(1), newline=False)
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    make_writer(tmp_path).append(state, [msg(2, date=at(2026, 10, 3))])
    assert message_ids(tmp_path) == [1, 2]


@pytest.mark.parametrize("tail", [b"null", b"[]", b"123", b'"x"'])
def test_a_last_line_that_is_valid_json_but_not_a_record_is_cut_not_a_crash(
    tmp_path: Path, tail: bytes
) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", line(1))
    path.write_bytes(path.read_bytes() + tail)
    recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == line(1) + b"\n"


def test_crlf_files_are_kept_as_they_are(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(line(1) + b"\r\n" + line(2) + b"\r\n")
    before = path.read_bytes()
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == before
    assert state.last_id == 2
    assert state.chunks["2026-10_001"].records == 2


def test_crlf_file_with_a_cut_last_line(tmp_path: Path) -> None:
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(line(1) + b"\r\n" + b'{"cut')
    recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == line(1) + b"\r\n"


def test_garbage_in_the_middle_is_kept_but_not_counted(tmp_path: Path) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", line(1), b"garbage", line(3))
    before = path.read_bytes()
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == before
    assert state.chunks["2026-10_001"] == ChunkInfo(2, 1, 3, len(before))
    assert state.last_id == 3


def test_blank_lines_at_the_end_are_harmless(tmp_path: Path) -> None:
    path = write_part(tmp_path, "2026-10_001.jsonl", line(1))
    path.write_bytes(path.read_bytes() + b"\n\n")
    before = path.read_bytes()
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert path.read_bytes() == before
    assert state.last_id == 1


def test_empty_part_gets_a_zero_chunk_and_does_not_disturb_floor(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-09_001.jsonl")
    write_part(tmp_path, "2026-10_001.jsonl", line(5), line(6))
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert state.chunks["2026-09_001"] == ChunkInfo(0, 0, 0, 0)
    assert state.floor_id == 5
    assert state.last_id == 6


def test_stale_temp_files_are_removed_and_real_files_kept(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(1))
    (tmp_path / ".state.json.tmp").write_bytes(b"{partial")
    (tmp_path / ".2026-10_002.jsonl.tmp").write_bytes(b"partial")
    (tmp_path / "keep.tmp").write_bytes(b"not hidden")
    (tmp_path / ".hidden").write_bytes(b"x")
    recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".hidden",
        "2026-10_001.jsonl",
        "keep.tmp",
        "state.json",
    ]


def test_state_missing_is_rebuilt_from_the_files(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-09_001.jsonl", line(10, 9), line(11, 9))
    write_part(tmp_path, "2026-10_001.jsonl", line(20), line(30))
    folder = tmp_path
    state = recover_chat(folder, now=NOW)
    assert state.chat_id == CHAT_ID
    assert state.phase == PHASE_RECOVER
    assert state.floor_id == 10
    assert state.last_id == 30
    assert state.backfill == BackfillState(done=False)
    assert state.title == folder.name
    assert state.username is None
    assert state.updated_at == NOW
    assert set(state.chunks) == {"2026-09_001", "2026-10_001"}
    assert_state_matches_files(tmp_path)


def test_state_rebuild_uses_the_fallback_title_when_given(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(1))
    state = recover_chat(tmp_path, now=NOW, fallback_title="Example Title")
    assert state.title == "Example Title"


@pytest.mark.parametrize(
    "garbage", [b"", b"{broken", b"[]", b"\xef\xbb\xbf{", b"\x00\x00", b'{"chat_id": "x"}']
)
def test_corrupt_state_is_treated_like_a_missing_one(tmp_path: Path, garbage: bytes) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(4), line(5))
    (tmp_path / "state.json").write_bytes(garbage)
    state = recover_chat(tmp_path, now=NOW)
    assert state.phase == PHASE_RECOVER
    assert state.floor_id == 4
    assert state.last_id == 5
    assert load_state(tmp_path) == state


def test_missing_state_without_records_and_without_fallback_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot recover"):
        recover_chat(tmp_path, now=NOW)
    assert not (tmp_path / "state.json").exists()


def test_missing_state_with_only_edit_records_and_no_fallback_is_an_error(tmp_path: Path) -> None:
    edit = EditRecord(CHAT_ID, 3, at(2026, 10, 2), NOW, "t")
    write_part(tmp_path, "2026-10_001.jsonl", record_to_line(edit).encode())
    with pytest.raises(ValueError, match="cannot recover"):
        recover_chat(tmp_path, now=NOW)


def test_missing_state_with_only_edit_records_uses_the_fallback_id(tmp_path: Path) -> None:
    edit = EditRecord(CHAT_ID, 3, at(2026, 10, 2), NOW, "t")
    write_part(tmp_path, "2026-10_001.jsonl", record_to_line(edit).encode())
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=-77)
    assert state.chat_id == -77
    assert state.last_id == 0
    assert state.floor_id == 0
    assert state.chunks["2026-10_001"].records == 1


def test_missing_state_in_an_empty_folder_with_fallback_gives_a_fresh_recover_state(
    tmp_path: Path,
) -> None:
    state = recover_chat(tmp_path / "new", now=NOW, fallback_chat_id=-5, fallback_title="T")
    assert (state.chat_id, state.title, state.last_id, state.floor_id) == (-5, "T", 0, 0)
    assert state.chunks == {}
    assert (tmp_path / "new" / "state.json").is_file()


def test_records_chat_id_beats_the_fallback(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(1))
    assert recover_chat(tmp_path, now=NOW, fallback_chat_id=999).chat_id == CHAT_ID


def test_existing_state_keeps_its_own_identity_and_phase(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    state = replace(state, phase=PHASE_LIVE, title="Kept", username="kept_user", floor_id=0)
    save_state(tmp_path, state)
    recovered = recover_chat(tmp_path, now=NOW + timedelta(hours=1), fallback_chat_id=5)
    assert (recovered.chat_id, recovered.phase, recovered.title) == (CHAT_ID, PHASE_LIVE, "Kept")
    assert recovered.username == "kept_user"
    assert recovered.updated_at == NOW + timedelta(hours=1)


def test_last_id_from_files_beats_a_lagging_state(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    path = tmp_path / "2026-10_001.jsonl"
    path.write_bytes(path.read_bytes() + line(2) + b"\n" + line(3) + b"\n")
    save_state(tmp_path, state)
    recovered = recover_chat(tmp_path, now=NOW)
    assert recovered.last_id == 3
    assert recovered.chunks["2026-10_001"].records == 3


def test_a_state_ahead_of_the_files_keeps_its_last_id(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    save_state(tmp_path, replace(state, last_id=50))
    assert recover_chat(tmp_path, now=NOW).last_id == 50


def test_unknown_parts_on_disk_are_added_to_chunks(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    write_part(tmp_path, "2026-10_002.jsonl", line(2))
    save_state(tmp_path, state)
    recovered = recover_chat(tmp_path, now=NOW)
    assert set(recovered.chunks) == {"2026-10_001", "2026-10_002"}
    assert recovered.last_id == 2
    assert recovered.floor_id == 0
    assert recovered.floor_reason is None


def test_oldest_part_deleted_by_hand_drops_the_chunk_and_raises_the_floor(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = fresh_state()
    for i in (10, 20, 30):
        state = writer.append(state, [msg(i, date=at(2026, 10, 1, 0, i))])
    (tmp_path / "2026-10_001.jsonl").unlink()
    recovered = recover_chat(tmp_path, now=NOW)
    assert set(recovered.chunks) == {"2026-10_002", "2026-10_003"}
    assert recovered.floor_id == 20
    assert recovered.floor_reason == FLOOR_REASON_MANUAL_DELETE
    assert recovered.last_id == 30


def test_floor_never_goes_down_when_parts_are_deleted(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = fresh_state()
    for i in (10, 20):
        state = writer.append(state, [msg(i, date=at(2026, 10, 1, 0, i))])
    save_state(tmp_path, replace(state, floor_id=500))
    (tmp_path / "2026-10_001.jsonl").unlink()
    assert recover_chat(tmp_path, now=NOW).floor_id == 500


def test_a_manual_trim_floor_reason_survives_when_nothing_is_missing(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    save_state(tmp_path, replace(state, floor_id=1, floor_reason="manual_trim_25"))
    recovered = recover_chat(tmp_path, now=NOW)
    assert (recovered.floor_id, recovered.floor_reason) == (1, "manual_trim_25")


def test_all_parts_gone_raises_the_floor_to_last_id_and_keeps_state(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(
        fresh_state(), [msg(1, date=at(2026, 10, 1)), msg(7, date=at(2026, 10, 2))]
    )
    (tmp_path / "2026-10_001.jsonl").unlink()
    recovered = recover_chat(tmp_path, now=NOW)
    assert recovered.chunks == {}
    assert recovered.floor_id == 7
    assert recovered.last_id == 7
    assert recovered.floor_reason == FLOOR_REASON_MANUAL_DELETE
    assert recovered.chat_id == state.chat_id


def test_state_with_no_chunks_and_no_parts_stays_untouched_apart_from_the_stamp(
    tmp_path: Path,
) -> None:
    save_state(tmp_path, fresh_state())
    recovered = recover_chat(tmp_path, now=NOW + timedelta(minutes=5))
    assert recovered.floor_id == 0
    assert recovered.floor_reason is None
    assert recovered.updated_at == NOW + timedelta(minutes=5)


def test_non_part_files_are_ignored(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(1))
    (tmp_path / "notes.jsonl").write_bytes(line(999) + b"\n")
    (tmp_path / "chat.json").write_bytes(b"[]")
    (tmp_path / "readme.txt").write_bytes(b"hi")
    (tmp_path / "2026-10_001.jsonl.bak").write_bytes(line(888) + b"\n")
    (tmp_path / "subdir").mkdir()
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert set(state.chunks) == {"2026-10_001"}
    assert state.last_id == 1
    assert (tmp_path / "notes.jsonl").read_bytes() == line(999) + b"\n"


def test_recover_is_idempotent(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-09_001.jsonl", line(1, 9), b'{"cut', newline=False)
    write_part(tmp_path, "2026-10_001.jsonl", line(2), line(3), newline=False)
    first = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    snapshot = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    second = recover_chat(tmp_path, now=NOW)
    assert second == first
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == snapshot


def test_recovered_state_matches_the_files_exactly(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-09_001.jsonl", line(1, 9), line(2, 9))
    write_part(tmp_path, "2026-10_001.jsonl", line(3), line(5), line(4))
    recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert_state_matches_files(tmp_path)
    assert part_names(tmp_path) == ["2026-09_001.jsonl", "2026-10_001.jsonl"]


def test_recovered_chunk_ids_use_min_and_max_even_when_unsorted(tmp_path: Path) -> None:
    write_part(tmp_path, "2026-10_001.jsonl", line(9), line(2), line(5))
    state = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    chunk = state.chunks["2026-10_001"]
    assert (chunk.first_id, chunk.last_id) == (2, 9)


def test_unicode_and_embedded_newlines_survive_recovery(tmp_path: Path) -> None:
    record = msg(1, date=at(2026, 10, 1), text=f"a\nb\r\n{LINE_SEP}{RU_LOWER}{EMOJI}")
    write_part(tmp_path, "2026-10_001.jsonl", record_to_line(record).encode())
    before = (tmp_path / "2026-10_001.jsonl").read_bytes()
    recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert (tmp_path / "2026-10_001.jsonl").read_bytes() == before


def test_recovery_leaves_files_closed(tmp_path: Path) -> None:
    import shutil

    folder = tmp_path / "chat"
    write_part(folder, "2026-10_001.jsonl", line(1), b"cut", newline=False)
    recover_chat(folder, now=NOW, fallback_chat_id=CHAT_ID)
    shutil.rmtree(folder)
    assert not folder.exists()
