# pyright: reportPrivateUsage=false
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport import trim
from chatimport.records import EditRecord, MessageRecord, Record
from chatimport.storage.state import ChunkInfo, StateUnreadable
from chatimport.trim import _plan_trim, preview_percent
from tests.unit.maintenance.helpers import at, build_chat, mmsg
from tests.unit.maintenance.test_trim import make_trimmer

if TYPE_CHECKING:
    from pathlib import Path

CHAT = -1001


def info(records: int) -> ChunkInfo:
    return ChunkInfo(records=records, first_id=1, last_id=records, bytes=100)


def dated(chat_id: int, ids: range, month: int) -> list[Record]:
    return [
        MessageRecord(chat_id, i, at(2026, month, 1 + i % 20, 12), at(2026, 10, 30), text="t")
        for i in ids
    ]


def test_plan_trim_with_nothing_to_remove_is_none() -> None:
    assert _plan_trim({"a": info(3)}, 25) is None
    assert _plan_trim({}, 50) is None


def test_plan_trim_cuts_a_boundary_part() -> None:
    plan = _plan_trim({"a": info(4), "b": info(4), "c": info(4)}, 50)
    assert plan is not None
    assert (plan.target, plan.whole, plan.boundary, plan.skip) == (6, ("a",), "b", 2)


def test_plan_trim_on_a_part_edge_removes_whole_parts_only() -> None:
    plan = _plan_trim({"a": info(4), "b": info(4)}, 50)
    assert plan is not None
    assert (plan.whole, plan.boundary, plan.skip) == (("a",), None, 0)


def test_plan_trim_that_consumes_every_part() -> None:
    plan = _plan_trim({"a": info(2), "b": info(2)}, 100)
    assert plan is not None
    assert (plan.whole, plan.boundary, plan.skip) == (("a", "b"), None, 0)


def test_preview_matches_a_real_trim(tmp_path: Path) -> None:
    chat = build_chat(
        tmp_path,
        CHAT,
        [dated(CHAT, range(1, 5), 7), dated(CHAT, range(5, 9), 8), dated(CHAT, range(9, 13), 9)],
    )
    preview = preview_percent(tmp_path, 50)
    (only,) = preview.chats
    assert preview.pct == 50
    assert (only.chat_id, only.title, only.records_total) == (CHAT, "Chat", 12)
    assert (only.records_deleted, only.parts_deleted) == (6, 1)
    assert only.oldest_after is not None
    assert only.oldest_after.month == 8
    assert (preview.records_deleted, preview.parts_deleted) == (6, 1)
    before = sum(p.stat().st_size for p in chat.folder.glob("*.jsonl"))
    assert 0 < preview.bytes_freed == only.bytes_freed < before


async def test_preview_agrees_with_the_real_trim(tmp_path: Path) -> None:
    chat = build_chat(tmp_path, CHAT, [dated(CHAT, range(1, 5), 7), dated(CHAT, range(5, 9), 8)])
    before = sum(p.stat().st_size for p in chat.folder.glob("*.jsonl"))
    (preview,) = preview_percent(tmp_path, 75).chats
    await make_trimmer(tmp_path, chat).trim_percent(75)
    after = sum(p.stat().st_size for p in chat.folder.glob("*.jsonl"))
    assert preview.bytes_freed == pytest.approx(before - after, abs=before // 4)
    assert preview.records_deleted == 6


def test_preview_of_a_tiny_chat_removes_nothing(tmp_path: Path) -> None:
    build_chat(tmp_path, CHAT, [[mmsg(1, chat_id=CHAT)]])
    (only,) = preview_percent(tmp_path, 25).chats
    assert (only.records_total, only.records_deleted, only.bytes_freed) == (1, 0, 0)
    assert only.oldest_after is None


def test_preview_can_be_limited_to_one_chat(tmp_path: Path) -> None:
    build_chat(tmp_path, CHAT, [dated(CHAT, range(1, 9), 7)], title="One")
    build_chat(tmp_path, -1002, [dated(-1002, range(1, 9), 7)], title="Two")
    assert len(preview_percent(tmp_path, 50).chats) == 2
    (only,) = preview_percent(tmp_path, 50, chat_id=-1002).chats
    assert only.chat_id == -1002
    assert preview_percent(tmp_path, 50, chat_id=5).chats == ()


def test_preview_leaves_out_unreadable_and_stateless_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_chat(tmp_path, CHAT, [dated(CHAT, range(1, 9), 7)])
    (tmp_path / "stray").mkdir()
    assert len(preview_percent(tmp_path, 50).chats) == 1

    def refuse(folder: Path) -> None:
        raise StateUnreadable(folder, OSError("busy"))

    monkeypatch.setattr(trim, "load_state", refuse)
    assert preview_percent(tmp_path, 50).chats == ()


def test_preview_rejects_other_percentages(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pct must be one of"):
        preview_percent(tmp_path, 30)


def test_a_vanished_part_falls_back_to_the_recorded_size(tmp_path: Path) -> None:
    chat = build_chat(tmp_path, CHAT, [dated(CHAT, range(1, 5), 7)])
    (part,) = chat.folder.glob("*.jsonl")
    assert trim._part_size(chat.folder, part.stem, info(4)) == part.stat().st_size
    part.unlink()
    assert trim._part_size(chat.folder, part.stem, info(4)) == 100


def edits(chat_id: int, ids: range) -> list[Record]:
    return [EditRecord(chat_id, i, at(2026, 9, 2), at(2026, 10, 30), "e") for i in ids]


def test_oldest_after_skips_leading_non_message_records(tmp_path: Path) -> None:
    build_chat(
        tmp_path,
        CHAT,
        [dated(CHAT, range(1, 5), 7), [*edits(CHAT, range(1, 3)), *dated(CHAT, range(5, 7), 8)]],
    )
    (only,) = preview_percent(tmp_path, 50).chats
    assert (only.parts_deleted, only.records_deleted) == (1, 4)
    assert only.oldest_after is not None
    assert only.oldest_after.month == 8


def test_oldest_after_is_none_when_nothing_but_edits_remain(tmp_path: Path) -> None:
    build_chat(tmp_path, CHAT, [dated(CHAT, range(1, 5), 7), edits(CHAT, range(1, 5))])
    (only,) = preview_percent(tmp_path, 50).chats
    assert only.records_deleted == 4
    assert only.oldest_after is None
