from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Literal

import pytest

from chatimport.records import DeleteRecord, EditRecord, MediaSavedRecord, MessageRecord, Record
from chatimport.runtime import ChatRegistry
from chatimport.storage.layout import STATE_FILE, list_parts
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import load_state, save_state
from chatimport.storage.writer import iter_records
from chatimport.trim import TRIM_LOG, Trimmer
from tests.fakes import NOW, FakeClock
from tests.unit.maintenance.helpers import (
    FakeController,
    assert_state_matches_files,
    at,
    build_chat,
    message_ids,
    mmsg,
    read_state,
)

CHAT = -1001


def make_trimmer(
    root: Path, *controllers: FakeController, clock: FakeClock | None = None
) -> Trimmer:
    registry = ChatRegistry()
    for controller in controllers:
        registry.add(controller)
    return Trimmer(root, registry, clock=clock or FakeClock(), max_chunk_bytes=1)


def layout(records: list[Record], style: str) -> list[list[Record]]:
    if style == "single":
        return [records]
    size = 1 if style == "each" else 2
    return [records[i : i + size] for i in range(0, len(records), size)]


def messages(count: int, chat_id: int = CHAT) -> list[Record]:
    return [mmsg(i, chat_id=chat_id) for i in range(1, count + 1)]


def trim_log_lines(root: Path) -> list[dict[str, object]]:
    path = root / TRIM_LOG
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def media_folder(chat: FakeController, month: str, names: list[str]) -> Path:
    month_dir = chat.folder / "media" / month
    month_dir.mkdir(parents=True)
    for name in names:
        (month_dir / name).write_bytes(b"x")
    return month_dir


def old_chat(
    root: Path, chat_id: int, title: str, month_days: list[tuple[int, int]]
) -> FakeController:
    batches: list[list[Record]] = [
        [MessageRecord(chat_id, number, at(2026, month, day, 12), NOW, text="t")]
        for number, (month, day) in enumerate(month_days, start=1)
    ]
    return build_chat(root, chat_id, batches, title=title)


@pytest.mark.parametrize("style", ["single", "each", "pairs"])
@pytest.mark.parametrize("count", [1, 2, 3, 4, 7, 100])
@pytest.mark.parametrize("pct", [25, 50, 75])
async def test_trim_removes_exactly_floor_of_the_share_of_records(
    tmp_path: Path, count: int, pct: int, style: str
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(count), style))

    report = await make_trimmer(root, chat).trim_percent(pct)

    removed = count * pct // 100
    assert report.trimmed_records == removed
    remaining = list(range(1, count + 1))[removed:]
    assert message_ids(chat) == remaining
    state = read_state(chat)
    assert state.last_id == count
    assert sum(c.records for c in state.chunks.values()) == len(remaining)
    assert_state_matches_files(chat)
    if removed:
        assert state.floor_id == removed + 1
        assert state.floor_reason == f"manual_trim_{pct}"
        assert report.per_chat == {CHAT: removed}
    else:
        assert state.floor_id == 0
        assert report.per_chat == {}


async def test_target_zero_leaves_every_byte_and_writes_no_log(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(3), "each"))
    before = {p.name: p.read_bytes() for p in chat.folder.iterdir()}

    report = await make_trimmer(root, chat).trim_percent(25)

    assert report.trimmed_records == 0
    assert report.deleted_parts == []
    assert {p.name: p.read_bytes() for p in chat.folder.iterdir()} == before
    assert not (root / TRIM_LOG).exists()


@pytest.mark.parametrize("pct", [0, 10, 26, 100, -25, 125])
async def test_invalid_percentages_are_rejected_before_touching_anything(
    tmp_path: Path, pct: int
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(4), "each"))

    with pytest.raises(ValueError, match="pct must be one of"):
        await make_trimmer(root, chat).trim_percent(pct)

    assert message_ids(chat) == [1, 2, 3, 4]


async def test_whole_parts_are_deleted_and_the_boundary_part_keeps_its_tail(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [messages(3), [mmsg(i, chat_id=CHAT) for i in (4, 5, 6)]])

    report = await make_trimmer(root, chat).trim_percent(50)

    assert [p.part for p in report.deleted_parts] == ["2026-09_001"]
    assert report.deleted_parts[0].records == 3
    assert report.deleted_parts[0].first_id == 1
    assert report.deleted_parts[0].last_id == 3
    assert message_ids(chat) == [4, 5, 6]
    assert [p.name for p in list_parts(chat.folder)] == ["2026-09_002.jsonl"]


async def test_boundary_cut_inside_one_part_keeps_the_rest_of_that_part(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [messages(4)])

    report = await make_trimmer(root, chat).trim_percent(75)

    assert report.deleted_parts == []
    assert report.trimmed_records == 3
    assert message_ids(chat) == [4]
    assert report.freed_bytes > 0
    assert_state_matches_files(chat)


async def test_freed_bytes_equal_the_real_shrink_of_the_folder(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(10), "pairs"))
    before = sum(p.stat().st_size for p in list_parts(chat.folder))

    report = await make_trimmer(root, chat).trim_percent(50)

    after = sum(p.stat().st_size for p in list_parts(chat.folder))
    assert report.freed_bytes == before - after


async def test_the_skip_counts_every_record_kind_not_only_messages(tmp_path: Path) -> None:
    root = tmp_path / "root"
    records: list[Record] = [
        mmsg(1, chat_id=CHAT),
        EditRecord(CHAT, 1, at(2026, 9, 10, 3), NOW, text="e"),
        mmsg(2, chat_id=CHAT),
        DeleteRecord(CHAT, (1,), NOW),
        mmsg(3, chat_id=CHAT),
        MediaSavedRecord(CHAT, 3, "media/2026-09/3.jpg", NOW),
        mmsg(4, chat_id=CHAT),
        mmsg(5, chat_id=CHAT),
    ]
    chat = build_chat(root, CHAT, [records], max_chunk_bytes=10**9)
    assert len(list(iter_records(chat.folder))) == 8

    report = await make_trimmer(root, chat).trim_percent(50)

    assert report.trimmed_records == 4
    assert len(list(iter_records(chat.folder))) == 4
    assert sum(c.records for c in read_state(chat).chunks.values()) == 4
    assert_state_matches_files(chat)


async def test_chat_with_only_edit_records_trims_without_crashing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    records: list[Record] = [
        EditRecord(CHAT, 5, at(2026, 9, 10, h), NOW, text="x") for h in range(1, 5)
    ]
    chat = build_chat(root, CHAT, [records], max_chunk_bytes=10**9)
    save_state(chat.folder, replace(read_state(chat), last_id=9))

    report = await make_trimmer(root, chat).trim_percent(50)

    assert report.trimmed_records == 2
    assert len(list(iter_records(chat.folder))) == 2
    assert read_state(chat).floor_id == 9
    assert_state_matches_files(chat)


async def test_percentages_apply_per_chat_not_over_the_total(tmp_path: Path) -> None:
    root = tmp_path / "root"
    small = build_chat(root, -1, layout(messages(4, -1), "single"), title="Small")
    big = build_chat(root, -2, layout(messages(100, -2), "pairs"), title="Big")

    report = await make_trimmer(root, small, big).trim_percent(50)

    assert report.per_chat == {-1: 2, -2: 50}
    assert message_ids(small) == [3, 4]
    assert message_ids(big) == list(range(51, 101))
    assert len(trim_log_lines(root)) == 2


async def test_trimming_one_chat_leaves_the_others_alone(tmp_path: Path) -> None:
    root = tmp_path / "root"
    a = build_chat(root, -1, layout(messages(4, -1), "each"), title="A")
    b = build_chat(root, -2, layout(messages(4, -2), "each"), title="B")

    report = await make_trimmer(root, a, b).trim_percent(50, chat_id=-2)

    assert report.per_chat == {-2: 2}
    assert message_ids(a) == [1, 2, 3, 4]
    assert message_ids(b) == [3, 4]


async def test_unknown_chat_is_a_quiet_no_op(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(4), "each"))

    report = await make_trimmer(root, chat).trim_percent(50, chat_id=999)

    assert report.trimmed_records == 0
    assert message_ids(chat) == [1, 2, 3, 4]


async def test_missing_folder_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    ghost = FakeController(-7, root / "ghost_-7")

    report = await make_trimmer(root, ghost).trim_percent(50)

    assert report.trimmed_records == 0
    assert not (root / "ghost_-7").exists()


@pytest.mark.parametrize("content", [b"", b"{broken", b"[]", b'{"chat_id": 1}'])
async def test_unreadable_state_means_nothing_is_deleted(tmp_path: Path, content: bytes) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(4), "each"))
    (chat.folder / STATE_FILE).write_bytes(content)

    report = await make_trimmer(root, chat).trim_percent(75)

    assert report.trimmed_records == 0
    assert message_ids(chat) == [1, 2, 3, 4]


async def test_floor_id_never_decreases(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(4), "each"))
    save_state(chat.folder, replace(read_state(chat), floor_id=1000))

    await make_trimmer(root, chat).trim_percent(50)

    assert read_state(chat).floor_id == 1000


async def test_trim_log_entry_is_complete_and_valid_json(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(8), "pairs"))
    clock = FakeClock(at(2026, 10, 1, 8, 30, 15))

    report = await make_trimmer(root, chat, clock=clock).trim_percent(50)

    (entry,) = trim_log_lines(root)
    assert entry == {
        "when": "2026-10-01T08:30:15Z",
        "kind": "manual",
        "chat_id": CHAT,
        "pct": 50,
        "parts": ["2026-09_001", "2026-09_002"],
        "records": 4,
        "bytes": report.freed_bytes,
        "reason": "manual_trim_50",
    }
    assert read_state(chat).updated_at == clock.now()


async def test_trim_log_is_appended_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(8), "each"))
    trimmer = make_trimmer(root, chat)

    await trimmer.trim_percent(25)
    await trimmer.trim_percent(25)

    assert len(trim_log_lines(root)) == 2


async def test_second_trim_trims_a_share_of_what_is_left(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(8), "each"))
    trimmer = make_trimmer(root, chat)

    await trimmer.trim_percent(50)
    second = await trimmer.trim_percent(50)

    assert message_ids(chat) == [7, 8]
    assert second.trimmed_records == 2
    assert read_state(chat).floor_id == 7


async def test_media_is_deleted_by_exact_message_id_prefix(tmp_path: Path) -> None:
    root = tmp_path / "root"
    ids = [1, 2, 3, 4, 12, 123, 1234]
    chat = build_chat(root, CHAT, [[mmsg(i, chat_id=CHAT) for i in ids]], max_chunk_bytes=10**9)
    month_dir = media_folder(
        chat,
        "2026-09",
        ["1.jpg", "2_1.jpg", "2_2.jpg", "12.mp4", "123.png", "1234.jpg", "99.jpg", "readme.txt"],
    )

    await make_trimmer(root, chat).trim_percent(50)

    assert sorted(p.name for p in month_dir.iterdir()) == [
        "12.mp4",
        "123.png",
        "1234.jpg",
        "99.jpg",
        "readme.txt",
    ]


async def test_media_id_prefix_must_match_the_whole_number(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(
        root,
        CHAT,
        [[mmsg(123, chat_id=CHAT)], [mmsg(1234, chat_id=CHAT)]],
    )
    month_dir = media_folder(chat, "2026-09", ["123_2.jpg", "1234.jpg"])

    await make_trimmer(root, chat).trim_percent(50)

    assert [p.name for p in month_dir.iterdir()] == ["1234.jpg"]


async def test_media_of_a_deleted_whole_part_goes_and_the_empty_month_dir_is_pruned(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(1, chat_id=CHAT)], [mmsg(2, chat_id=CHAT)]])
    month_dir = media_folder(chat, "2026-09", ["1.jpg", "1_1.jpg"])

    await make_trimmer(root, chat).trim_percent(50)

    assert not month_dir.exists()
    assert (chat.folder / "media").is_dir()


async def test_media_of_other_months_is_not_touched(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(1, chat_id=CHAT)], [mmsg(2, chat_id=CHAT)]])
    other = media_folder(chat, "2026-08", ["1.jpg"])

    await make_trimmer(root, chat).trim_percent(50)

    assert (other / "1.jpg").exists()


async def test_media_of_the_cut_boundary_records_is_deleted_but_kept_tail_stays(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [messages(4)], max_chunk_bytes=10**9)
    month_dir = media_folder(chat, "2026-09", ["1.jpg", "2.jpg", "3.jpg", "4.jpg"])

    await make_trimmer(root, chat).trim_percent(50)

    assert sorted(p.name for p in month_dir.iterdir()) == ["3.jpg", "4.jpg"]


async def test_a_media_file_that_cannot_be_deleted_does_not_abort_the_trim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(1, chat_id=CHAT)], [mmsg(2, chat_id=CHAT)]])
    media_folder(chat, "2026-09", ["1.jpg"])
    real_unlink = Path.unlink

    def guarded(self: Path, missing_ok: bool = False) -> None:
        if self.name == "1.jpg":
            raise PermissionError("locked")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", guarded)

    with caplog.at_level("WARNING"):
        await make_trimmer(root, chat).trim_percent(50)

    assert message_ids(chat) == [2]
    assert "cannot delete a media file" in caplog.text
    assert "cannot remove an empty media folder" not in caplog.text


async def test_undeletable_empty_media_folder_only_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, [[mmsg(1, chat_id=CHAT)], [mmsg(2, chat_id=CHAT)]])
    media_folder(chat, "2026-09", ["1.jpg"])

    def refuse(self: Path) -> None:
        raise PermissionError("busy")

    monkeypatch.setattr(Path, "rmdir", refuse)

    with caplog.at_level("WARNING"):
        await make_trimmer(root, chat).trim_percent(50)

    assert "cannot remove an empty media folder" in caplog.text
    assert message_ids(chat) == [2]


async def test_trim_waits_for_a_holder_of_the_controller_lock(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(4), "each"))
    trimmer = make_trimmer(root, chat)

    async with chat.lock:
        task = asyncio.create_task(trimmer.trim_percent(50))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not task.done()
        assert message_ids(chat) == [1, 2, 3, 4]

    report = await task
    assert report.trimmed_records == 2
    assert not chat.lock.locked()


async def test_crash_while_cutting_the_boundary_part_recovers_consistently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    tail: list[Record] = [mmsg(i, chat_id=CHAT) for i in (2, 3, 4, 5)]
    chat = build_chat(root, CHAT, [[mmsg(1, chat_id=CHAT)], tail])

    def explode(path: Path, data: bytes) -> None:
        raise OSError("disk went away")

    monkeypatch.setattr("chatimport.trim.atomic_write_bytes", explode)

    with pytest.raises(OSError, match="disk went away"):
        await make_trimmer(root, chat).trim_percent(50)

    assert not chat.lock.locked()
    recovered = recover_chat(chat.folder, now=NOW)
    ids = message_ids(chat)
    assert ids == sorted(set(ids))
    assert ids[-1] == 5
    assert recovered.last_id == 5
    assert recovered.floor_id == ids[0]
    assert_state_matches_files(chat)


async def test_crash_before_the_state_is_saved_is_repaired_by_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    chat = build_chat(root, CHAT, layout(messages(8), "each"))

    def explode(folder: Path, state: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr("chatimport.trim.save_state", explode)

    with pytest.raises(OSError, match="power cut"):
        await make_trimmer(root, chat).trim_percent(50)

    assert len(read_state(chat).chunks) == 8
    recovered = recover_chat(chat.folder, now=NOW)
    assert message_ids(chat) == [5, 6, 7, 8]
    assert recovered.floor_id == 5
    assert recovered.last_id == 8
    assert_state_matches_files(chat)
    assert not (root / TRIM_LOG).exists()


async def test_delete_oldest_part_picks_the_globally_oldest_part_across_chats(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    a = old_chat(root, -1, "A", [(5, 3), (6, 3)])
    b = old_chat(root, -2, "B", [(4, 3), (7, 3)])
    c = old_chat(root, -3, "C", [(5, 20)])
    trimmer = make_trimmer(root, a, b, c)

    order: list[tuple[int, str]] = []
    for _ in range(10):
        part = await trimmer.delete_oldest_part(protect_recent_days=30)
        if part is None:
            break
        order.append((part.chat_id, part.part))

    assert order == [
        (-2, "2026-04_001"),
        (-1, "2026-05_001"),
        (-3, "2026-05_001"),
        (-1, "2026-06_001"),
        (-2, "2026-07_001"),
    ]


async def test_delete_oldest_part_only_considers_the_oldest_part_of_each_chat(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(5, 3), (10, 28)])
    trimmer = make_trimmer(root, chat)

    first = await trimmer.delete_oldest_part(protect_recent_days=30)
    second = await trimmer.delete_oldest_part(protect_recent_days=30)

    assert first is not None
    assert first.part == "2026-05_001"
    assert second is None
    assert message_ids(chat) == [2]


async def test_delete_oldest_part_raises_the_floor_and_logs(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(5, 3), (6, 3), (7, 3)])

    part = await make_trimmer(root, chat).delete_oldest_part(protect_recent_days=30)

    assert part is not None
    assert (part.records, part.first_id, part.last_id) == (1, 1, 1)
    state = read_state(chat)
    assert state.floor_id == 2
    assert state.floor_reason == "disk"
    assert list(state.chunks) == ["2026-06_001", "2026-07_001"]
    assert_state_matches_files(chat)
    (entry,) = trim_log_lines(root)
    assert entry["kind"] == "disk"
    assert entry["pct"] is None
    assert entry["parts"] == ["2026-05_001"]
    assert entry["bytes"] == part.bytes


async def test_deleting_the_last_part_raises_the_floor_to_its_last_id(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(5, 3)])

    part = await make_trimmer(root, chat).delete_oldest_part(protect_recent_days=1)

    assert part is not None
    state = read_state(chat)
    assert state.chunks == {}
    assert state.floor_id == 1
    assert state.last_id == 1


@pytest.mark.parametrize(
    ("delta", "eligible"),
    [
        (timedelta(seconds=-1), True),
        (timedelta(0), False),
        (timedelta(seconds=1), False),
    ],
)
async def test_protect_recent_days_boundary_is_exclusive_at_the_limit(
    tmp_path: Path, delta: timedelta, eligible: bool
) -> None:
    root = tmp_path / "root"
    stamp = NOW - timedelta(days=30) + delta
    chat = build_chat(root, CHAT, [[MessageRecord(CHAT, 1, stamp, NOW, text="x")]], title="Edge")

    part = await make_trimmer(root, chat).delete_oldest_part(protect_recent_days=30)

    assert (part is not None) is eligible


async def test_a_part_is_protected_by_its_newest_record_not_its_first(tmp_path: Path) -> None:
    root = tmp_path / "root"
    records: list[Record] = [
        MessageRecord(CHAT, 1, at(2026, 10, 1), NOW, text="old"),
        DeleteRecord(CHAT, (1,), at(2026, 10, 27)),
    ]
    chat = build_chat(root, CHAT, [records], max_chunk_bytes=10**9)
    assert len(list_parts(chat.folder)) == 1

    part = await make_trimmer(root, chat).delete_oldest_part(protect_recent_days=20)

    assert part is None
    assert message_ids(chat) == [1]


async def test_a_part_without_messages_falls_back_to_its_month_start(tmp_path: Path) -> None:
    root = tmp_path / "root"
    records: list[Record] = [DeleteRecord(CHAT, (7,), at(2026, 3, 5))]
    chat = build_chat(root, CHAT, [records], max_chunk_bytes=10**9)

    part = await make_trimmer(root, chat).delete_oldest_part(protect_recent_days=30)

    assert part is not None
    assert part.first_id == 0


async def test_delete_oldest_part_returns_none_without_chats_or_state(tmp_path: Path) -> None:
    root = tmp_path / "root"
    ghost = FakeController(-9, root / "ghost")
    broken = old_chat(root, -1, "A", [(1, 1)])
    (broken.folder / STATE_FILE).write_text("nope", encoding="utf-8")

    assert await make_trimmer(root).delete_oldest_part(30) is None
    assert await make_trimmer(root, ghost, broken).delete_oldest_part(30) is None


async def test_delete_oldest_part_with_no_parts_in_state_is_none(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(1, 1)])
    save_state(chat.folder, replace(read_state(chat), chunks={}))

    assert await make_trimmer(root, chat).delete_oldest_part(30) is None
    assert len(list_parts(chat.folder)) == 1


async def test_chunks_whose_files_are_gone_are_ignored_by_the_disk_trim(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(1, 1), (2, 1)])
    list_parts(chat.folder)[0].unlink()

    part = await make_trimmer(root, chat).delete_oldest_part(30)

    assert part is not None
    assert part.part == "2026-02_001"


async def test_media_of_a_part_deleted_for_disk_space_goes_with_it(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(5, 3), (6, 3)])
    month_dir = media_folder(chat, "2026-05", ["1.jpg"])

    await make_trimmer(root, chat).delete_oldest_part(30)

    assert not month_dir.exists()


async def test_disk_trim_waits_for_the_lock(tmp_path: Path) -> None:
    root = tmp_path / "root"
    chat = old_chat(root, -1, "A", [(5, 3), (6, 3)])
    trimmer = make_trimmer(root, chat)

    async with chat.lock:
        task = asyncio.create_task(trimmer.delete_oldest_part(30))
        for _ in range(20):
            await asyncio.sleep(0)
        assert not task.done()

    assert await task is not None


class _HookLock(asyncio.Lock):
    """Runs a callback right before its second acquisition."""

    def __init__(self, hook: object) -> None:
        super().__init__()
        self._hook = hook
        self._count = 0

    async def acquire(self) -> Literal[True]:
        self._count += 1
        if self._count == 2 and callable(self._hook):
            self._hook()
        return await super().acquire()


async def test_candidate_that_lost_its_eligibility_before_the_lock_is_skipped(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    victim = old_chat(root, -1, "A", [(5, 3), (6, 3)])
    other = old_chat(root, -2, "B", [(7, 3), (8, 3)])
    hooked = FakeController(
        -1, victim.folder, "A", _HookLock(lambda: (victim.folder / STATE_FILE).unlink())
    )

    part = await make_trimmer(root, hooked, other).delete_oldest_part(30)

    assert part is not None
    assert part.chat_id == -2
    assert load_state(victim.folder) is None
    assert len(list_parts(victim.folder)) == 2


async def test_candidate_whose_state_vanishes_inside_the_final_step_gives_the_next_one(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    victim = old_chat(root, -1, "A", [(5, 3)])
    other = old_chat(root, -2, "B", [(7, 3)])
    raced = FakeController(
        -1, victim.folder, "A", _HookLock(lambda: (victim.folder / STATE_FILE).unlink())
    )

    part = await make_trimmer(root, raced, other).delete_oldest_part(30)

    assert part is not None
    assert part.chat_id == -2
