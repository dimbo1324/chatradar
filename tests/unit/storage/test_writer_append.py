from __future__ import annotations

import random
import shutil
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from chatimport.records import (
    DeleteRecord,
    EditRecord,
    MediaSavedRecord,
    MessageRecord,
    Record,
    record_to_line,
)
from chatimport.storage import writer as writer_module
from chatimport.storage.layout import MAX_PART_NUMBER, list_parts, part_file_name
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import ChatState, ChunkInfo, load_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.storage.helpers import (
    EMOJI,
    HE,
    LINE_SEP,
    PARA_SEP,
    RU_LOWER,
    ZH,
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


def line_size(record: Record) -> int:
    return len(record_to_line(record).encode("utf-8")) + 1


def test_empty_batch_returns_the_same_state_and_touches_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "chat"
    state = fresh_state()
    assert make_writer(folder).append(state, []) is state
    assert not folder.exists()


def test_first_append_creates_folder_part_and_state(tmp_path: Path) -> None:
    folder = tmp_path / "deep" / "chat"
    record = msg(7, date=at(2026, 10, 5, 12))
    new = make_writer(folder).append(fresh_state(), [record])
    assert part_names(folder) == ["2026-10_001.jsonl"]
    assert new.last_id == 7
    assert new.chunks["2026-10_001"] == ChunkInfo(1, 7, 7, line_size(record))
    assert new.updated_at == NOW
    assert load_state(folder) == new
    assert_state_matches_files(folder)


def test_append_does_not_mutate_the_state_it_was_given(tmp_path: Path) -> None:
    state = fresh_state()
    make_writer(tmp_path).append(state, [msg(1, date=at(2026, 10, 1))])
    assert state.chunks == {}
    assert state.last_id == 0


def test_unsorted_batch_across_months_lands_ascending_in_each_month(tmp_path: Path) -> None:
    records = [
        msg(30, date=at(2026, 10, 3)),
        msg(10, date=at(2026, 9, 3)),
        msg(40, date=at(2026, 10, 4)),
        msg(20, date=at(2026, 9, 4)),
        msg(5, date=at(2026, 8, 30)),
    ]
    make_writer(tmp_path).append(fresh_state(), records)
    assert part_names(tmp_path) == ["2026-08_001.jsonl", "2026-09_001.jsonl", "2026-10_001.jsonl"]
    assert message_ids(tmp_path) == [5, 10, 20, 30, 40]
    assert_state_matches_files(tmp_path)


def test_a_batch_with_interleaved_months_writes_each_month_once(tmp_path: Path) -> None:
    records = [
        msg(1, date=at(2026, 10, 1)),
        msg(2, date=at(2026, 9, 1)),
        msg(3, date=at(2026, 10, 2)),
    ]
    state = make_writer(tmp_path).append(fresh_state(), records)
    assert state.chunks["2026-10_001"].records == 2
    assert state.chunks["2026-09_001"].records == 1


@pytest.mark.parametrize(
    ("moment", "month"),
    [
        (datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC), "2026-10"),
        (datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC), "2026-09"),
        (datetime(2026, 9, 30, 23, 59, 59, 999999, tzinfo=UTC), "2026-09"),
        (datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC), "2026-12"),
        (datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC), "2027-01"),
        (datetime(2026, 10, 1, 2, 59, 59, tzinfo=timezone(timedelta(hours=3))), "2026-09"),
        (datetime(2026, 10, 1, 3, 0, 0, tzinfo=timezone(timedelta(hours=3))), "2026-10"),
        (datetime(2026, 9, 30, 20, 59, 59, tzinfo=timezone(timedelta(hours=-3))), "2026-09"),
        (datetime(2026, 9, 30, 21, 0, 0, tzinfo=timezone(timedelta(hours=-3))), "2026-10"),
    ],
)
def test_message_goes_to_the_utc_month_of_its_date(
    tmp_path: Path, moment: datetime, month: str
) -> None:
    make_writer(tmp_path).append(fresh_state(), [msg(1, date=moment)])
    assert part_names(tmp_path) == [part_file_name(month, 1)]


def test_message_dated_exactly_at_a_month_boundary_and_one_second_before_split(
    tmp_path: Path,
) -> None:
    records = [msg(1, date=at(2026, 9, 30, 23, 59, 59)), msg(2, date=at(2026, 10, 1, 0, 0, 0))]
    make_writer(tmp_path).append(fresh_state(), records)
    assert part_names(tmp_path) == ["2026-09_001.jsonl", "2026-10_001.jsonl"]


def test_edit_and_delete_and_media_marks_go_to_the_month_of_the_event(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(5, date=at(2026, 9, 20))])
    edit = EditRecord(CHAT_ID, 5, edit_date=at(2026, 10, 2), fetched_at=at(2026, 10, 2), text="x")
    delete = DeleteRecord(CHAT_ID, (5,), fetched_at=at(2026, 11, 3))
    saved = MediaSavedRecord(CHAT_ID, 5, "media/5.jpg", fetched_at=at(2026, 12, 1, 0, 0, 0))
    writer.append(state, [edit, delete, saved])
    assert part_names(tmp_path) == [
        "2026-09_001.jsonl",
        "2026-10_001.jsonl",
        "2026-11_001.jsonl",
        "2026-12_001.jsonl",
    ]
    kinds = [type(r).__name__ for r in all_records(tmp_path)]
    assert kinds == ["MessageRecord", "EditRecord", "DeleteRecord", "MediaSavedRecord"]


def test_only_messages_move_last_id_and_it_never_goes_down(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(10, date=at(2026, 10, 1))])
    edit = EditRecord(CHAT_ID, 99, edit_date=at(2026, 10, 2), fetched_at=NOW)
    delete = DeleteRecord(CHAT_ID, (500, 600), fetched_at=NOW)
    state = writer.append(state, [edit, delete])
    assert state.last_id == 10
    state = writer.append(state, [msg(3, date=at(2026, 10, 3))])
    assert state.last_id == 10
    state = writer.append(state, [msg(11, date=at(2026, 10, 4))])
    assert state.last_id == 11


def test_edit_records_count_as_records_but_not_as_ids_in_chunks(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    edit = EditRecord(CHAT_ID, 77, edit_date=at(2026, 10, 2), fetched_at=NOW)
    state = writer.append(fresh_state(), [edit])
    chunk = state.chunks["2026-10_001"]
    assert (chunk.records, chunk.first_id, chunk.last_id) == (1, 0, 0)
    state = writer.append(state, [msg(5, date=at(2026, 10, 3)), msg(2, date=at(2026, 10, 3))])
    chunk = state.chunks["2026-10_001"]
    assert (chunk.records, chunk.first_id, chunk.last_id) == (3, 2, 5)
    assert state.last_id == 5


def test_batch_is_never_split_even_with_a_one_byte_threshold(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    batch = [msg(i, date=at(2026, 10, 1, 1, i)) for i in range(1, 6)]
    state = writer.append(fresh_state(), batch)
    assert part_names(tmp_path) == ["2026-10_001.jsonl"]
    assert state.chunks["2026-10_001"].records == 5
    state = writer.append(state, [msg(6, date=at(2026, 10, 2))])
    state = writer.append(state, [msg(7, date=at(2026, 10, 2, 1))])
    assert part_names(tmp_path) == ["2026-10_001.jsonl", "2026-10_002.jsonl", "2026-10_003.jsonl"]
    assert message_ids(tmp_path) == [1, 2, 3, 4, 5, 6, 7]
    assert_state_matches_files(tmp_path)


def test_part_whose_size_equals_the_threshold_is_full_and_one_byte_less_is_not(
    tmp_path: Path,
) -> None:
    first = msg(1, date=at(2026, 10, 1))
    size = line_size(first)

    exact = tmp_path / "exact"
    writer = make_writer(exact, max_bytes=size)
    state = writer.append(fresh_state(), [first])
    writer.append(state, [msg(2, date=at(2026, 10, 2))])
    assert part_names(exact) == ["2026-10_001.jsonl", "2026-10_002.jsonl"]

    below = tmp_path / "below"
    writer = make_writer(below, max_bytes=size + 1)
    state = writer.append(fresh_state(), [first])
    writer.append(state, [msg(2, date=at(2026, 10, 2))])
    assert part_names(below) == ["2026-10_001.jsonl"]


def test_threshold_of_one_byte_gives_one_part_per_batch(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = fresh_state()
    for i in range(1, 8):
        state = writer.append(state, [msg(i, date=at(2026, 10, 1, i))])
    assert len(list_parts(tmp_path)) == 7
    assert_state_matches_files(tmp_path)


def test_a_new_month_starts_at_part_one_regardless_of_other_months(tmp_path: Path) -> None:
    writer = make_writer(tmp_path, max_bytes=1)
    state = fresh_state()
    for i in range(3):
        state = writer.append(state, [msg(i + 1, date=at(2026, 9, 1 + i))])
    writer.append(state, [msg(10, date=at(2026, 10, 1))])
    assert part_names(tmp_path)[-1] == "2026-10_001.jsonl"


def test_chunk_accounting_stays_exact_after_many_random_appends(tmp_path: Path) -> None:
    rng = random.Random(20261029)  # noqa: S311 - seeded test data, not security
    writer = make_writer(tmp_path, max_bytes=700)
    state = fresh_state()
    next_id = 1
    expected_ids: list[int] = []
    for _ in range(80):
        batch: list[Record] = []
        for _ in range(rng.randint(1, 6)):
            when = at(2026, rng.choice([8, 9, 10]), rng.randint(1, 28), rng.randint(0, 23))
            batch.append(msg(next_id, date=when, text="t" * rng.randint(0, 60)))
            expected_ids.append(next_id)
            next_id += 1
        if rng.random() < 0.3:
            batch.append(EditRecord(CHAT_ID, rng.randint(1, next_id), at(2026, 10, 5), NOW, "e"))
        rng.shuffle(batch)
        state = writer.append(state, batch)
    assert sorted(message_ids(tmp_path)) == expected_ids
    disk_state = assert_state_matches_files(tmp_path)
    assert disk_state == state


def test_parts_of_one_month_keep_messages_ordered_across_part_boundaries(
    tmp_path: Path,
) -> None:
    writer = make_writer(tmp_path, max_bytes=300)
    state = fresh_state()
    for i in range(1, 30):
        state = writer.append(state, [msg(i, date=at(2026, 10, 1, 0, i))])
    assert len(list_parts(tmp_path)) > 3
    assert message_ids(tmp_path) == list(range(1, 30))


def test_append_extends_a_part_that_exists_but_is_not_in_chunks(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(
        fresh_state(), [msg(1, date=at(2026, 10, 1)), msg(2, date=at(2026, 10, 1))]
    )
    amnesiac = ChatState.from_dict({**state.to_dict(), "chunks": {}})
    state = writer.append(amnesiac, [msg(3, date=at(2026, 10, 2))])
    chunk = state.chunks["2026-10_001"]
    assert (chunk.records, chunk.first_id, chunk.last_id) == (3, 1, 3)
    assert chunk.bytes == (tmp_path / "2026-10_001.jsonl").stat().st_size


def test_an_existing_part_below_the_threshold_is_reused_even_if_old(tmp_path: Path) -> None:
    folder = tmp_path
    (folder / "2026-10_001.jsonl").write_bytes(b"")
    state = make_writer(folder).append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    assert part_names(folder) == ["2026-10_001.jsonl"]
    assert state.chunks["2026-10_001"].records == 1


def test_files_are_closed_after_every_append_so_the_folder_can_be_deleted(tmp_path: Path) -> None:
    folder = tmp_path / "chat"
    writer = make_writer(folder, max_bytes=200)
    state = fresh_state()
    for i in range(1, 6):
        state = writer.append(state, [msg(i, date=at(2026, 10, i))])
    shutil.rmtree(folder)
    assert not folder.exists()


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain",
        "line1\nline2",
        "crlf\r\ntext\r",
        f"{LINE_SEP}separator{PARA_SEP}",
        "\x85next line\x0b\x0c\x1c\x1d\x1e",
        f"{RU_LOWER} {EMOJI} {ZH} {HE}",
        "nul\x00inside",
        'quote" back\\slash',
        "x" * 100_000,
        chr(0xFEFF) + "bom first",
    ],
)
def test_awkward_text_survives_one_record_per_line(tmp_path: Path, text: str) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(
        fresh_state(), [msg(1, date=at(2026, 10, 1), text=text), msg(2, date=at(2026, 10, 1))]
    )
    raw = (tmp_path / "2026-10_001.jsonl").read_bytes()
    assert raw.count(b"\n") == 2
    records = all_records(tmp_path)
    assert [r.msg_id for r in records if isinstance(r, MessageRecord)] == [1, 2]
    first = records[0]
    assert isinstance(first, MessageRecord)
    assert first.text == text
    assert state.chunks["2026-10_001"].records == 2


def test_a_lone_surrogate_in_text_does_not_poison_the_batch(tmp_path: Path) -> None:
    writer = make_writer(tmp_path)
    batch = [msg(1, date=at(2026, 10, 1), text="bad \ud83d half"), msg(2, date=at(2026, 10, 1))]
    writer.append(fresh_state(), batch)
    assert message_ids(tmp_path) == [1, 2]


def test_huge_ids_are_written_and_accounted(tmp_path: Path) -> None:
    big = 2**62
    state = make_writer(tmp_path).append(
        fresh_state(), [msg(big, date=at(2026, 10, 1)), msg(big - 1, date=at(2026, 10, 1))]
    )
    assert state.last_id == big
    assert state.chunks["2026-10_001"].first_id == big - 1
    assert message_ids(tmp_path) == [big - 1, big]


def test_part_number_limit_raises_instead_of_writing_a_1000th_part(tmp_path: Path) -> None:
    (tmp_path / part_file_name("2026-10", MAX_PART_NUMBER)).write_bytes(b"x" * 10)
    writer = make_writer(tmp_path, max_bytes=5)
    with pytest.raises(ValueError, match="999"):
        writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    assert len(list_parts(tmp_path)) == 1


def test_the_last_allowed_part_is_still_appended_to_while_below_the_threshold(
    tmp_path: Path,
) -> None:
    path = tmp_path / part_file_name("2026-10", MAX_PART_NUMBER)
    path.write_bytes(b"")
    make_writer(tmp_path, max_bytes=10**6).append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    assert message_ids(tmp_path) == [1]
    assert part_names(tmp_path) == [path.name]


def test_crash_between_data_and_state_is_aligned_by_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = make_writer(tmp_path)
    state = writer.append(fresh_state(), [msg(1, date=at(2026, 10, 1))])
    before = (tmp_path / "state.json").read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(writer_module, "save_state", boom)
    with pytest.raises(OSError, match="power cut"):
        writer.append(state, [msg(2, date=at(2026, 10, 1)), msg(3, date=at(2026, 11, 1))])
    monkeypatch.undo()

    assert (tmp_path / "state.json").read_bytes() == before
    assert message_ids(tmp_path) == [1, 2, 3]
    recovered = recover_chat(tmp_path, now=NOW)
    assert recovered.last_id == 3
    assert_state_matches_files(tmp_path)
    again = make_writer(tmp_path).append(recovered, [msg(4, date=at(2026, 11, 2))])
    assert message_ids(tmp_path) == [1, 2, 3, 4]
    assert again.chunks["2026-11_001"].records == 2


def test_crash_on_the_very_first_append_still_recovers_with_a_fallback_chat_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(writer_module, "save_state", boom)
    with pytest.raises(OSError, match="power cut"):
        make_writer(tmp_path).append(fresh_state(), [msg(9, date=at(2026, 10, 1))])
    monkeypatch.undo()
    assert load_state(tmp_path) is None
    recovered = recover_chat(tmp_path, now=NOW, fallback_chat_id=CHAT_ID)
    assert recovered.last_id == 9
    assert recovered.chat_id == CHAT_ID


def test_update_state_stamps_the_injected_clock_and_persists(tmp_path: Path) -> None:
    stamp = datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)
    writer = ChunkWriter(tmp_path, 1000, clock=lambda: stamp)
    state = writer.update_state(fresh_state())
    assert state.updated_at == stamp
    assert load_state(tmp_path) == state


def test_default_clock_is_timezone_aware_utc(tmp_path: Path) -> None:
    state = ChunkWriter(tmp_path, 1000).update_state(fresh_state())
    assert state.updated_at.tzinfo is not None
    assert state.updated_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - state.updated_at) < timedelta(minutes=1)
