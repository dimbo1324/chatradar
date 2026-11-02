# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import shutil
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import search_indexer
from chatimport.records import DeleteRecord, EditRecord, MediaSavedRecord, record_to_bytes
from chatimport.runtime import ChatRegistry
from chatimport.search_index import PartMark, open_writer
from chatimport.search_indexer import (
    UNFINISHED,
    WINDOW,
    IndexBuilder,
    PartCursor,
    StepResult,
)
from chatimport.search_types import IndexState, IndexStatus
from chatimport.storage.layout import list_parts
from chatimport.storage.state import StateUnreadable, save_state
from chatimport.trim import Trimmer
from tests.fakes import CHAT_ID, NOW, FakeClock, msg
from tests.unit.storage.search_helpers import OTHER_CHAT, Archive, Rig, utc

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

BUILDING = IndexState.BUILDING
READY = IndexState.READY


@pytest.fixture
def make_rig(tmp_path: Path) -> Iterator[Callable[..., Rig]]:
    rigs: list[Rig] = []

    def make(batch: int = search_indexer.BATCH_RECORDS) -> Rig:
        rig = Rig(tmp_path, batch)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.close()


def alpha(*ids: int, chat_id: int = CHAT_ID) -> list[Any]:
    return [msg(i, chat_id=chat_id, text=f"alpha {i}") for i in ids]


def touch_later(path: Path) -> None:
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))


def only_part(archive: Archive) -> Path:
    (part,) = list_parts(archive.folder)
    return part


def test_the_initial_build_goes_chat_by_chat_and_serves_the_finished_ones(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    Archive(tmp_path, CHAT_ID, "Alpha").add(*alpha(1, 2, 3))
    Archive(tmp_path, OTHER_CHAT, "Beta").add(
        *(msg(i, chat_id=OTHER_CHAT, text=f"beta {i}") for i in (1, 2, 3))
    )
    rig = make_rig()
    assert rig.builder.step() == StepResult(True, BUILDING, 3, 6, NOW)
    assert rig.ids("alpha") == [3, 2, 1]
    assert rig.ids("beta") == []
    assert rig.reader.status() == IndexStatus(BUILDING, 3, 6, NOW)

    assert rig.run() == [
        StepResult(True, BUILDING, 6, 6, NOW),
        StepResult(False, READY, 6, 6, NOW),
    ]
    assert rig.ids("beta") == [3, 2, 1]
    assert rig.reader.status() == IndexStatus(READY, 6, 6, NOW)
    assert [(c.title, c.messages) for c in rig.reader.chats()] == [("Alpha", 3), ("Beta", 3)]


def test_a_small_batch_spreads_one_chat_over_several_steps(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1, 2, 3, 4, 5, 6))
    monkeypatch.setattr(search_indexer, "BLOCK_BYTES", 400)
    rig = make_rig(batch=2)
    results = rig.run()
    assert [(r.more, r.state, r.indexed, r.total) for r in results] == [
        (True, BUILDING, 2, 6),
        (True, BUILDING, 4, 6),
        (True, BUILDING, 6, 6),
        (True, BUILDING, 6, 6),
        (False, READY, 6, 6),
    ]
    assert rig.ids("alpha") == [6, 5, 4, 3, 2, 1]


def test_a_line_longer_than_a_block_is_still_read(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1, 2, 3, 4, 5, 6))
    monkeypatch.setattr(search_indexer, "BLOCK_BYTES", 50)
    rig = make_rig()
    results = rig.run()
    assert [(r.more, r.state, r.indexed) for r in results] == [
        (True, BUILDING, 6),
        (False, READY, 6),
    ]
    assert rig.ids("alpha") == [6, 5, 4, 3, 2, 1]


def test_a_restart_continues_from_the_watermark_without_duplicates(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1, 2, 3, 4, 5, 6))
    monkeypatch.setattr(search_indexer, "BLOCK_BYTES", 400)
    first = make_rig(batch=2)
    assert first.builder.step().indexed == 2
    first.close()
    second = make_rig(batch=2)
    results = second.run()
    assert results[0] == StepResult(True, BUILDING, 4, 6, NOW)
    assert results[-1] == StepResult(False, READY, 6, 6, NOW)
    assert second.find("alpha").total == 6
    assert second.ids("alpha") == [6, 5, 4, 3, 2, 1]


def test_a_failed_batch_is_redone_from_scratch_without_duplicates(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1, 2, 3))
    rig = make_rig()
    real = rig.index.apply
    calls: list[int] = []

    def flaky(*args: Any, **kwargs: Any) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(rig.index, "apply", flaky)
    with pytest.raises(OSError, match="disk full"):
        rig.builder.step()
    assert rig.index.indexed_count() == 0
    assert rig.run()[-1] == StepResult(False, READY, 3, 3, NOW)
    assert rig.find("alpha").total == 3
    assert len(calls) == 2


def test_new_messages_are_appended_from_the_watermark(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1, 2, 3))
    rig = make_rig()
    rig.run()
    archive.add(*alpha(4, 5))
    assert rig.run() == [
        StepResult(True, READY, 5, 5, NOW),
        StepResult(False, READY, 5, 5, NOW),
    ]
    assert rig.ids("alpha") == [5, 4, 3, 2, 1]
    part = only_part(archive)
    assert rig.index.marks(CHAT_ID)[part.name].offset == part.stat().st_size
    assert rig.index.chat_rows()[CHAT_ID].gen == 0


def test_an_idle_pass_writes_nothing(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1, 2, 3))
    rig = make_rig()
    rig.run()
    writes: list[str] = []
    real_status = rig.index.set_status
    real_apply = rig.index.apply

    def status(*args: Any) -> None:
        writes.append("status")
        real_status(*args)

    def apply(*args: Any) -> int:
        writes.append("apply")
        return real_apply(*args)

    monkeypatch.setattr(rig.index, "set_status", status)
    monkeypatch.setattr(rig.index, "apply", apply)
    assert rig.run() == [StepResult(False, READY, 3, 3, NOW)]
    assert writes == []


def test_a_new_month_is_a_new_part(tmp_path: Path, make_rig: Callable[..., Rig]) -> None:
    archive = Archive(tmp_path)
    archive.add(
        msg(1, date=utc(2026, 9, 10), text="alpha september"),
        msg(2, date=utc(2026, 10, 10), text="alpha october"),
    )
    rig = make_rig()
    rig.run()
    archive.add(msg(3, date=utc(2026, 11, 10), text="alpha november"))
    rig.run()
    assert rig.ids("alpha") == [3, 2, 1]
    assert sorted(rig.index.marks(CHAT_ID)) == [
        "2026-09_001.jsonl",
        "2026-10_001.jsonl",
        "2026-11_001.jsonl",
    ]


def test_an_edit_in_a_later_part_updates_the_message(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(msg(1, date=utc(2026, 10, 5, 10), text="original text"))
    archive.add(EditRecord(CHAT_ID, 1, utc(2026, 11, 2, 9), NOW, text="november edit"))
    rig = make_rig()
    rig.run()
    assert rig.ids("original text") == []
    page = rig.find("november edit")
    assert [(hit.msg_id, hit.edited) for hit in page.hits] == [(1, True)]


def test_an_edit_in_an_earlier_part_waits_for_its_message(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(EditRecord(CHAT_ID, 1, utc(2026, 9, 1, 9), NOW, text="early edit"))
    archive.add(msg(1, date=utc(2026, 11, 5, 10), text="late message"))
    assert sorted(p.name for p in list_parts(archive.folder)) == [
        "2026-09_001.jsonl",
        "2026-11_001.jsonl",
    ]
    rig = make_rig()
    rig.run()
    assert rig.ids("late message") == []
    assert rig.ids("early edit") == [1]


def test_a_delete_record_removes_the_message_on_the_next_pass(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1, 2, 3))
    rig = make_rig()
    rig.run()
    archive.add(DeleteRecord(CHAT_ID, (2,), NOW))
    rig.run()
    assert rig.ids("alpha") == [3, 1]
    assert rig.index.indexed_count() == 2


def test_service_messages_and_media_marks_are_not_indexed(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    Archive(tmp_path).add(
        msg(1, text="alpha joined", service="join"),
        MediaSavedRecord(CHAT_ID, 2, "file.jpg", NOW),
        msg(2, text="alpha hello"),
    )
    rig = make_rig()
    rig.run()
    assert rig.ids("alpha") == [2]


def test_a_cut_last_line_waits_until_it_is_complete(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    rig = make_rig()
    rig.run()
    part = only_part(archive)
    line = record_to_bytes(alpha(2)[0])
    with part.open("ab") as handle:
        handle.write(line[:100])
    rig.run()
    assert rig.ids("alpha") == [1]
    assert rig.index.marks(CHAT_ID)[part.name].offset < part.stat().st_size
    with part.open("ab") as handle:
        handle.write(line[100:])
    rig.run()
    assert rig.ids("alpha") == [2, 1]
    assert rig.index.marks(CHAT_ID)[part.name].offset == part.stat().st_size


def test_unreadable_and_blank_lines_are_skipped(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    rig = make_rig()
    rig.run()
    with only_part(archive).open("ab") as handle:
        handle.write(b"garbage\n\n")
    archive.add(*alpha(2))
    rig.run()
    assert rig.ids("alpha") == [2, 1]


def test_a_folder_that_looks_like_a_part_is_not_a_part(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    archive.part("2026-08_001.jsonl").mkdir()
    rig = make_rig()
    rig.run()
    assert rig.ids("alpha") == [1]
    assert "2026-08_001.jsonl" not in rig.index.marks(CHAT_ID)


def test_a_part_of_blank_lines_is_consumed(tmp_path: Path, make_rig: Callable[..., Rig]) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    archive.part("2026-08_001.jsonl").write_bytes(b"\n\n")
    rig = make_rig()
    rig.run()
    assert rig.ids("alpha") == [1]
    assert rig.index.marks(CHAT_ID)["2026-08_001.jsonl"].offset == 2


def three_parts(tmp_path: Path) -> Archive:
    archive = Archive(tmp_path, max_bytes=500)
    for i in range(1, 7):
        archive.add(*alpha(i))
    assert [p.name for p in list_parts(archive.folder)] == [
        "2026-09_001.jsonl",
        "2026-09_002.jsonl",
        "2026-09_003.jsonl",
    ]
    return archive


def test_a_deleted_oldest_part_drops_only_its_messages(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = three_parts(tmp_path)
    rig = make_rig()
    rig.run()
    list_parts(archive.folder)[0].unlink()
    assert rig.run() == [StepResult(False, READY, 4, 4, NOW)]
    assert rig.ids("alpha") == [6, 5, 4, 3]
    assert rig.index.chat_rows()[CHAT_ID].gen == 0
    assert sorted(rig.index.marks(CHAT_ID)) == ["2026-09_002.jsonl", "2026-09_003.jsonl"]


def test_the_state_floor_also_drops_older_messages_of_a_kept_part(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = three_parts(tmp_path)
    rig = make_rig()
    rig.run()
    save_state(archive.folder, replace(archive.state, floor_id=5))
    list_parts(archive.folder)[0].unlink()
    rig.run()
    assert rig.ids("alpha") == [6, 5]


def test_removing_every_part_empties_the_chat(tmp_path: Path, make_rig: Callable[..., Rig]) -> None:
    archive = three_parts(tmp_path)
    rig = make_rig()
    rig.run()
    for part in list_parts(archive.folder):
        part.unlink()
    rig.run()
    assert rig.ids("alpha") == []
    assert rig.index.indexed_count() == 0


async def test_a_manual_trim_with_a_cut_part_is_reconciled(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(*range(900, 912)))
    rig = make_rig()
    rig.run()
    assert rig.find("alpha").total == 12
    trimmer = Trimmer(tmp_path, ChatRegistry(), clock=FakeClock(), max_chunk_bytes=10**7)
    report = await trimmer.trim_percent(50, CHAT_ID)
    assert report.trimmed_records == 6
    rig.run()
    assert sorted(rig.ids("alpha")) == [906, 907, 908, 909, 910, 911]
    row = rig.index.chat_rows()[CHAT_ID]
    assert (row.gen, row.reconciling, row.messages) == (1, False, 6)


def test_a_part_that_shrank_is_reconciled_without_a_gap(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1, 2))
    rig = make_rig()
    rig.run()
    part = only_part(archive)
    part.write_bytes(part.read_bytes().split(b"\n")[0] + b"\n")
    first = rig.builder.step()
    assert first.more is True
    assert rig.ids("alpha") == [2, 1]
    assert rig.index.chat_rows()[CHAT_ID].reconciling is True
    rig.run()
    assert rig.ids("alpha") == [1]
    row = rig.index.chat_rows()[CHAT_ID]
    assert (row.gen, row.reconciling, row.messages) == (1, False, 1)


def test_a_rewrite_of_the_same_size_is_found_by_the_checksums(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(msg(1, text="alpha one"), msg(2, text="alpha two"))
    rig = make_rig()
    rig.run()
    part = only_part(archive)
    part.write_bytes(part.read_bytes().replace(b"alpha two", b"omega two"))
    touch_later(part)
    rig.run()
    assert rig.ids("alpha") == [1]
    assert rig.ids("omega") == [2]
    assert rig.index.chat_rows()[CHAT_ID].gen == 1


def big_archive(tmp_path: Path) -> Archive:
    archive = Archive(tmp_path)
    archive.add(*alpha(*range(900, 930)))
    assert only_part(archive).stat().st_size > 2 * WINDOW
    return archive


def test_appending_to_a_large_part_resumes_without_a_reconcile(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = big_archive(tmp_path)
    rig = make_rig()
    rig.run()
    archive.add(*alpha(930))
    rig.run()
    assert rig.find("alpha").total == 31
    assert rig.index.chat_rows()[CHAT_ID].gen == 0


@pytest.mark.parametrize(
    ("needle", "replacement", "changed"),
    [
        (b'"text":"alpha 900"', b'"text":"omega 900"', 900),
        (b'"text":"alpha 929"', b'"text":"omega 929"', 929),
    ],
)
def test_a_change_in_the_first_or_the_last_bytes_of_a_large_part_is_found(
    tmp_path: Path,
    make_rig: Callable[..., Rig],
    needle: bytes,
    replacement: bytes,
    changed: int,
) -> None:
    archive = big_archive(tmp_path)
    rig = make_rig()
    rig.run()
    part = only_part(archive)
    part.write_bytes(part.read_bytes().replace(needle, replacement))
    touch_later(part)
    rig.run()
    assert rig.ids(f"omega {changed}") == [changed]
    assert rig.ids(f"alpha {changed}") == []
    assert rig.index.chat_rows()[CHAT_ID].gen == 1


def test_a_month_rewritten_by_a_backfill_is_reconciled(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(*range(900, 906)))
    rig = make_rig()
    rig.run()
    archive.state = archive.writer.merge_month(archive.state, "2026-10", alpha(895))
    rig.run()
    assert rig.find("alpha").total == 7
    assert 895 in rig.ids("alpha")
    assert rig.index.chat_rows()[CHAT_ID].gen == 1


def test_a_reconcile_that_stopped_before_its_sweep_is_finished_by_the_next_builder(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1, 2))
    first = make_rig()
    first.run()
    part = only_part(archive)
    part.write_bytes(part.read_bytes().split(b"\n")[0] + b"\n")

    def crash(_chat_id: int) -> None:
        raise RuntimeError("stopped")

    monkeypatch.setattr(first.index, "finish_reconcile", crash)
    with pytest.raises(RuntimeError, match="stopped"):
        first.run()
    row = first.index.chat_rows()[CHAT_ID]
    assert (row.reconciling, row.messages) == (True, 2)
    first.close()

    second = make_rig()
    assert second.run() == [
        StepResult(True, BUILDING, 1, 2, NOW),
        StepResult(False, READY, 1, 1, NOW),
    ]
    row = second.index.chat_rows()[CHAT_ID]
    assert (row.reconciling, row.messages) == (False, 1)
    assert second.ids("alpha") == [1]


def test_a_chat_with_a_journal_is_left_for_later_and_keeps_the_index_building(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    journal = archive.folder / ".2026-09.commit.json"
    journal.write_text("{}", encoding="utf-8")
    rig = make_rig()
    assert rig.run() == [StepResult(False, BUILDING, 0, 1, None)]
    journal.unlink()
    results = rig.run()
    assert results[-1] == StepResult(False, READY, 1, 1, NOW)
    assert rig.ids("alpha") == [1]


def test_a_journal_does_not_unready_a_finished_index(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    rig = make_rig()
    rig.run()
    archive.add(*alpha(2))
    journal = archive.folder / ".2026-09.commit.json"
    journal.write_text("{}", encoding="utf-8")
    assert rig.run() == [StepResult(False, READY, 1, 1, NOW)]
    journal.unlink()
    rig.run()
    assert rig.ids("alpha") == [2, 1]


@pytest.mark.parametrize("damage", ["missing", "broken"])
def test_a_chat_without_a_readable_state_is_skipped_until_it_has_one(
    tmp_path: Path, make_rig: Callable[..., Rig], damage: str
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    state_file = archive.folder / "state.json"
    if damage == "missing":
        state_file.unlink()
    else:
        state_file.write_text("not json", encoding="utf-8")
    rig = make_rig()
    assert rig.run() == [StepResult(False, READY, 0, 0, NOW)]
    save_state(archive.folder, archive.state)
    rig.run()
    assert rig.ids("alpha") == [1]


def test_an_unreadable_state_skips_the_chat_but_keeps_its_rows(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    rig = make_rig()
    rig.run()
    archive.add(*alpha(2))
    real = search_indexer.load_state

    def locked(folder: Path) -> None:
        raise StateUnreadable(folder, OSError("busy"))

    monkeypatch.setattr(search_indexer, "load_state", locked)
    rig.run()
    assert rig.ids("alpha") == [1]
    assert CHAT_ID in rig.index.chat_rows()
    monkeypatch.setattr(search_indexer, "load_state", real)
    rig.run()
    assert rig.ids("alpha") == [2, 1]


def test_a_copy_of_a_chat_folder_is_not_indexed_twice(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1, 2))
    shutil.copytree(archive.folder, tmp_path / "zz_copy")
    rig = make_rig()
    rig.run()
    assert rig.find("alpha").total == 2
    assert rig.index.chat_rows()[CHAT_ID].folder == archive.folder.name


def test_a_removed_chat_folder_drops_the_chat(tmp_path: Path, make_rig: Callable[..., Rig]) -> None:
    first = Archive(tmp_path, CHAT_ID, "Alpha")
    first.add(*alpha(1))
    Archive(tmp_path, OTHER_CHAT, "Beta").add(*alpha(1, chat_id=OTHER_CHAT))
    rig = make_rig()
    rig.run()
    shutil.rmtree(first.folder)
    rig.run()
    assert [hit.chat_id for hit in rig.find("alpha").hits] == [OTHER_CHAT]
    assert set(rig.index.chat_rows()) == {OTHER_CHAT}
    assert rig.index.marks(CHAT_ID) == {}


def test_a_missing_data_folder_drops_nothing(tmp_path: Path) -> None:
    index_root = tmp_path / "index"
    index_root.mkdir()
    index = open_writer(index_root)
    try:
        index.upsert_chat(1, "Chat", None, "chat_folder")
        index.apply(1, alpha(1, chat_id=1))
        builder = IndexBuilder(index, tmp_path / "missing", lambda: NOW)
        assert builder.step() == StepResult(False, READY, 1, 1, NOW)
        assert set(index.chat_rows()) == {1}
    finally:
        index.close()


def test_an_unlistable_data_folder_is_survived(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1))
    rig = make_rig()
    rig.run()

    def refuse(_root: Path) -> Iterator[Path]:
        raise PermissionError("denied")

    monkeypatch.setattr(search_indexer, "iter_chat_folders", refuse)
    assert rig.run() == [StepResult(False, READY, 1, 1, NOW)]
    assert set(rig.index.chat_rows()) == {CHAT_ID}


def test_a_chat_that_cannot_be_listed_is_skipped(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1))
    real = search_indexer._listing

    def broken(_folder: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(search_indexer, "_listing", broken)
    rig = make_rig()
    assert rig.run() == [StepResult(False, BUILDING, 0, 1, None)]
    monkeypatch.setattr(search_indexer, "_listing", real)
    rig.run()
    assert rig.ids("alpha") == [1]


def test_trimmed_history_is_kept_until_the_first_message_can_be_read(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = three_parts(tmp_path)
    rig = make_rig()
    rig.run()
    list_parts(archive.folder)[0].unlink()
    real = search_indexer.first_message

    def broken(_paths: Any) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(search_indexer, "first_message", broken)
    rig.run()
    assert rig.ids("alpha") == [6, 5, 4, 3, 2, 1]
    monkeypatch.setattr(search_indexer, "first_message", real)
    rig.run()
    assert rig.ids("alpha") == [6, 5, 4, 3]


def test_a_part_that_cannot_be_read_is_retried_on_the_next_pass(
    tmp_path: Path, make_rig: Callable[..., Rig], monkeypatch: pytest.MonkeyPatch
) -> None:
    Archive(tmp_path).add(*alpha(1, 2, 3))
    real = PartCursor.read_lines
    calls: list[int] = []

    def flaky(self: PartCursor, limit: int) -> list[bytes] | None:
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("locked by another program")
        return real(self, limit)

    monkeypatch.setattr(PartCursor, "read_lines", flaky)
    rig = make_rig()
    assert rig.run()[-1] == StepResult(False, BUILDING, 0, 3, NOW)
    assert rig.run()[-1] == StepResult(False, READY, 3, 3, NOW)
    assert rig.ids("alpha") == [3, 2, 1]


def test_a_renamed_chat_updates_its_title_and_link(
    tmp_path: Path, make_rig: Callable[..., Rig]
) -> None:
    archive = Archive(tmp_path)
    archive.add(*alpha(1))
    rig = make_rig()
    rig.run()
    assert rig.reader.chats()[0].title == "Chat"
    save_state(archive.folder, replace(archive.state, title="Renamed", username="renamed_pub"))
    rig.run()
    assert rig.reader.chats()[0].title == "Renamed"
    hit = rig.find("alpha").hits[0]
    assert (hit.chat_title, hit.link) == ("Renamed", "https://t.me/renamed_pub/1")


def test_the_cursor_reads_whole_lines_only(tmp_path: Path) -> None:
    path = tmp_path / "part"
    path.write_bytes(b"one\ntwo\npart")
    cursor = PartCursor(path, 12, 1)
    assert cursor.read_lines(1024) == [b"one", b"two"]
    assert cursor.offset == 8
    assert cursor.read_lines(1024) is None
    mark = cursor.mark(complete=True)
    assert (mark.part, mark.offset, mark.size, mark.mtime_ns) == ("part", 8, 12, 1)
    assert cursor.mark(complete=False).size == UNFINISHED


def test_the_cursor_skips_blank_lines_and_widens_for_a_long_line(tmp_path: Path) -> None:
    path = tmp_path / "part"
    path.write_bytes(b"\n\n")
    assert PartCursor(path, 2, 1).read_lines(1024) == []
    path.write_bytes(b"abcdefghij\n\nk\n")
    cursor = PartCursor(path, 14, 1)
    assert cursor.read_lines(3) == [b"abcdefghij", b"k"]
    assert cursor.offset == 14


def test_the_cursor_keeps_only_the_first_and_last_bytes(tmp_path: Path) -> None:
    path = tmp_path / "part"
    data = (b"x" * 99 + b"\n") * 100
    path.write_bytes(data)
    cursor = PartCursor(path, len(data), 1)
    lines = cursor.read_lines(len(data))
    assert lines is not None
    assert len(lines) == 100
    assert cursor.head == data[:WINDOW]
    assert cursor.tail == data[-WINDOW:]
    resumed = PartCursor.resume(path, len(data), 1, cursor.mark(complete=True))
    assert resumed is not None
    assert (resumed.offset, resumed.head, resumed.tail) == (cursor.offset, cursor.head, cursor.tail)


def test_the_cursor_refuses_a_part_that_no_longer_matches(tmp_path: Path) -> None:
    path = tmp_path / "part"
    path.write_bytes(b"one\ntwo\n")
    cursor = PartCursor(path, 8, 1)
    cursor.read_lines(1024)
    mark = cursor.mark(complete=True)
    assert PartCursor.resume(path, 3, 1, mark) is None
    path.write_bytes(b"one\nTWO\n")
    assert PartCursor.resume(path, 8, 1, mark) is None
    path.write_bytes(b"ONE\ntwo\n")
    assert PartCursor.resume(path, 8, 1, mark) is None
    path.write_bytes(b"one\ntwo\n")
    assert PartCursor.resume(path, 8, 1, mark) is not None
    assert PartCursor.resume(path, 8, 1, PartMark("part", 0, 8, 1, 0, 0)) is not None
