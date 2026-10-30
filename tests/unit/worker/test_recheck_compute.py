"""`compute_recheck`: what a comparison of the last N days with Telegram must produce."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.recheck import compute_recheck
from chatimport.records import (
    DETECTED_EVENT,
    DETECTED_RECHECK,
    DeleteRecord,
    EditRecord,
    MediaInfo,
    MediaSavedRecord,
    MessageRecord,
    Record,
    record_sort_id,
)
from chatimport.storage.state import PHASE_LIVE, ChatState, new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import CHAT_ID, NOW, FakeGateway, msg

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

DAYS = 7
SINCE = NOW - timedelta(days=DAYS)


def m(msg_id: int, hours_ago: float = 24, **kwargs: Any) -> MessageRecord:
    return msg(msg_id, date=NOW - timedelta(hours=hours_ago), **kwargs)


def photo(**kwargs: Any) -> MediaInfo:
    return MediaInfo(type="photo", mime="image/jpeg", size=10, **kwargs)


def build(folder: Path, records: Sequence[Record], *, floor_id: int = 0) -> ChatState:
    writer = ChunkWriter(folder, 10**9, lambda: NOW)
    state = replace(new_state(CHAT_ID, "t", None, NOW), phase=PHASE_LIVE, floor_id=floor_id)
    return writer.append(state, records)


def telegram(*records: MessageRecord) -> FakeGateway:
    gateway = FakeGateway()
    gateway.chats[CHAT_ID] = {r.msg_id: r for r in records}
    return gateway


async def recheck(
    folder: Path,
    state: ChatState,
    gateway: FakeGateway,
    *,
    edits: bool = True,
    deletes: bool = True,
    now: datetime = NOW,
    days: int = DAYS,
) -> list[Record]:
    return await compute_recheck(
        gateway, folder, state, now=now, days=days, track_edits=edits, track_deletes=deletes
    )


def apply(folder: Path, state: ChatState, result: Sequence[Record]) -> ChatState:
    return ChunkWriter(folder, 10**9, lambda: NOW).append(state, result)


async def test_identical_history_yields_nothing(tmp_path: Path) -> None:
    records = [m(i, 30 - i) for i in range(1, 20)]
    state = build(tmp_path, records)

    assert await recheck(tmp_path, state, telegram(*records)) == []


async def test_a_newer_edit_date_with_the_same_text_is_an_edit(tmp_path: Path) -> None:
    state = build(tmp_path, [m(1), m(2)])
    edited = m(1, edit_date=NOW - timedelta(hours=2))

    result = await recheck(tmp_path, state, telegram(edited, m(2)))

    assert result == [
        EditRecord(
            chat_id=CHAT_ID,
            msg_id=1,
            edit_date=NOW - timedelta(hours=2),
            fetched_at=NOW,
            text="text 1",
            media=None,
            detected_by=DETECTED_RECHECK,
        )
    ]


@pytest.mark.parametrize(
    ("stored", "remote", "differs"),
    [
        (None, None, False),
        (-3, -3, False),
        (-3, -4, False),
        (-3, -2, True),
        (None, -2, True),
    ],
)
async def test_edit_date_comparison_is_strictly_newer_wins(
    tmp_path: Path, stored: int | None, remote: int | None, differs: bool
) -> None:
    def at(hours: int | None) -> datetime | None:
        return None if hours is None else NOW + timedelta(hours=hours)

    state = build(tmp_path, [m(1, edit_date=at(stored))])

    result = await recheck(tmp_path, state, telegram(m(1, edit_date=at(remote))))

    assert bool(result) is differs


async def test_a_text_only_difference_is_an_edit_stamped_with_the_recheck_time(
    tmp_path: Path,
) -> None:
    state = build(tmp_path, [m(1, text="old")])

    [edit] = await recheck(tmp_path, state, telegram(m(1, text="new")))

    assert isinstance(edit, EditRecord)
    assert (edit.text, edit.edit_date, edit.fetched_at) == ("new", NOW, NOW)


async def test_whitespace_and_case_in_text_count_as_differences(tmp_path: Path) -> None:
    state = build(tmp_path, [m(1, text="Hello"), m(2, text="a b")])

    result = await recheck(tmp_path, state, telegram(m(1, text="hello"), m(2, text="a  b")))

    assert sorted(r.msg_id for r in result if isinstance(r, EditRecord)) == [1, 2]


@pytest.mark.parametrize(
    ("stored", "remote", "differs"),
    [
        (photo(), photo(), False),
        (photo(file="2026-10/1.jpg"), photo(), False),
        (photo(file="2026-10/1.jpg"), photo(file="other.jpg"), False),
        (photo(), None, True),
        (None, photo(), True),
        (photo(), MediaInfo(type="video", mime="image/jpeg", size=10), True),
        (photo(), MediaInfo(type="photo", mime="image/jpeg", size=11), True),
    ],
)
async def test_media_differences_ignore_only_the_saved_file(
    tmp_path: Path, stored: MediaInfo | None, remote: MediaInfo | None, differs: bool
) -> None:
    state = build(tmp_path, [m(1, media=stored)])

    result = await recheck(tmp_path, state, telegram(m(1, media=remote)))

    assert bool(result) is differs


async def test_a_message_missing_on_telegram_is_reported_deleted(tmp_path: Path) -> None:
    state = build(tmp_path, [m(1), m(2), m(3), m(4)])

    result = await recheck(tmp_path, state, telegram(m(1), m(3)))

    assert result == [DeleteRecord(CHAT_ID, (2, 4), NOW, DETECTED_RECHECK)]


async def test_a_recorded_deletion_is_not_reported_again(tmp_path: Path) -> None:
    state = build(tmp_path, [m(1), m(2), m(3)])
    gateway = telegram(m(1), m(3))

    first = await recheck(tmp_path, state, gateway)
    state = apply(tmp_path, state, first)

    assert len(first) == 1
    assert await recheck(tmp_path, state, gateway) == []


async def test_a_deleted_message_that_telegram_still_returns_is_not_edited(
    tmp_path: Path,
) -> None:
    deleted = DeleteRecord(CHAT_ID, (1,), NOW - timedelta(hours=1), DETECTED_EVENT)
    state = build(tmp_path, [m(1, text="old"), m(2), deleted])

    result = await recheck(tmp_path, state, telegram(m(1, text="new"), m(2)))

    assert result == []


async def test_a_gap_is_filled_with_the_telegram_copy(tmp_path: Path) -> None:
    present = [m(1), m(2), m(4)]
    state = replace(build(tmp_path, present), last_id=5)
    missing = m(3)

    result = await recheck(tmp_path, state, telegram(*present, missing, m(5)))

    assert result == [missing, m(5)]


async def test_messages_newer_than_last_id_are_not_requested(tmp_path: Path) -> None:
    state = build(tmp_path, [m(1), m(2)])
    gateway = telegram(m(1), m(2), m(3))

    assert await recheck(tmp_path, state, gateway) == []
    assert ("iter_window", (CHAT_ID, SINCE, 2)) in gateway.calls


async def test_everything_below_the_floor_is_ignored(tmp_path: Path) -> None:
    state = build(tmp_path, [m(5), m(6), m(7)], floor_id=5)
    gateway = telegram(m(1), m(2), m(5), m(6, text="changed"), m(7))

    result = await recheck(tmp_path, state, gateway)

    assert [(type(r).__name__, record_sort_id(r)) for r in result] == [("EditRecord", 6)]


async def test_the_floor_message_itself_is_still_compared(tmp_path: Path) -> None:
    state = build(tmp_path, [m(5, text="old"), m(6)], floor_id=5)

    result = await recheck(tmp_path, state, telegram(m(5, text="new"), m(6)))

    assert [r.msg_id for r in result if isinstance(r, EditRecord)] == [5]


async def test_a_trimmed_floor_message_that_is_not_stored_is_not_resurrected(
    tmp_path: Path,
) -> None:
    state = build(tmp_path, [m(6), m(7)], floor_id=5)

    result = await recheck(tmp_path, state, telegram(m(5), m(6), m(7)))

    assert result == []


async def test_nothing_is_compared_when_the_floor_has_reached_last_id(tmp_path: Path) -> None:
    state = build(tmp_path, [m(5)], floor_id=5)
    gateway = telegram(m(5, text="changed"))

    assert await recheck(tmp_path, state, gateway) == []
    assert gateway.count("iter_window") == 0


async def test_an_empty_telegram_window_never_deletes_anything(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state = build(tmp_path, [m(1), m(2)])

    with caplog.at_level(logging.WARNING, logger="chatimport.recheck"):
        result = await recheck(tmp_path, state, telegram())

    assert result == []
    assert any("empty window" in r.getMessage() for r in caplog.records)


async def test_an_empty_window_on_both_sides_is_quietly_empty(tmp_path: Path) -> None:
    old = m(1, hours_ago=24 * 30)
    state = build(tmp_path, [old])

    assert await recheck(tmp_path, state, telegram(old)) == []


async def test_the_window_includes_the_exact_start_and_excludes_one_second_before(
    tmp_path: Path,
) -> None:
    on_edge = msg(1, date=SINCE)
    just_before = msg(2, date=SINCE - timedelta(seconds=1))
    just_after = msg(3, date=SINCE + timedelta(seconds=1))
    state = build(tmp_path, [on_edge, just_before, just_after])

    deleted = await recheck(tmp_path, state, telegram(just_after))
    kept = await recheck(tmp_path, state, telegram(on_edge, just_after))

    assert deleted == [DeleteRecord(CHAT_ID, (1,), NOW, DETECTED_RECHECK)]
    assert kept == []


async def test_a_message_exactly_at_the_window_start_missing_from_the_files_is_filled(
    tmp_path: Path,
) -> None:
    on_edge = msg(2, date=SINCE)
    state = replace(build(tmp_path, [msg(1, date=SINCE + timedelta(hours=1)), m(3)]), last_id=3)

    result = await recheck(
        tmp_path, state, telegram(on_edge, m(3), msg(1, date=SINCE + timedelta(hours=1)))
    )

    assert result == [on_edge]


@pytest.mark.parametrize(
    ("edits", "deletes", "expected"),
    [
        (True, True, ["gap:3", "edit:5", "delete:7"]),
        (False, True, ["gap:3", "delete:7"]),
        (True, False, ["gap:3", "edit:5"]),
        (False, False, ["gap:3"]),
    ],
)
async def test_tracking_switches_only_disable_their_own_record_kind(
    tmp_path: Path, edits: bool, deletes: bool, expected: list[str]
) -> None:
    state = replace(build(tmp_path, [m(1), m(5, text="old"), m(7)]), last_id=7)
    gateway = telegram(m(1), m(3), m(5, text="new"))

    result = await recheck(tmp_path, state, gateway, edits=edits, deletes=deletes)

    labels = [
        f"gap:{r.msg_id}"
        if isinstance(r, MessageRecord)
        else f"edit:{r.msg_id}"
        if isinstance(r, EditRecord)
        else f"delete:{max(r.msg_ids)}"
        for r in result
        if not isinstance(r, MediaSavedRecord)
    ]
    assert labels == expected


async def test_the_result_is_ordered_by_message_id(tmp_path: Path) -> None:
    state = replace(build(tmp_path, [m(2), m(5, text="old"), m(9), m(12)]), last_id=12)
    gateway = telegram(m(2), m(5, text="new"), m(8), m(12))

    result = await recheck(tmp_path, state, gateway)

    assert [record_sort_id(r) for r in result] == [5, 8, 9]


async def test_applying_the_result_makes_the_next_recheck_empty(tmp_path: Path) -> None:
    state = replace(
        build(tmp_path, [m(i, 40 - i) for i in (1, 2, 3, 4, 6, 7)]),
        last_id=8,
    )
    gateway = telegram(
        m(1, 39),
        m(2, 38, text="rewritten"),
        m(3, 37, edit_date=NOW - timedelta(hours=3)),
        m(5, 35),
        m(6, 34, media=photo()),
        m(8, 32),
    )

    first = await recheck(tmp_path, state, gateway)
    state = apply(tmp_path, state, first)

    assert {type(r) for r in first} == {EditRecord, DeleteRecord, MessageRecord}
    assert await recheck(tmp_path, state, gateway) == []


async def test_edit_then_edit_back_is_followed_in_both_directions(tmp_path: Path) -> None:
    state = build(tmp_path, [m(1, text="A")])

    [to_b] = await recheck(
        tmp_path, state, telegram(m(1, text="B", edit_date=NOW - timedelta(hours=5)))
    )
    state = apply(tmp_path, state, [to_b])
    assert (
        await recheck(tmp_path, state, telegram(m(1, text="B", edit_date=NOW - timedelta(hours=5))))
        == []
    )

    back = telegram(m(1, text="A", edit_date=NOW - timedelta(hours=4)))
    [to_a] = await recheck(tmp_path, state, back)
    state = apply(tmp_path, state, [to_a])

    assert isinstance(to_a, EditRecord)
    assert to_a.text == "A"
    assert await recheck(tmp_path, state, back) == []


async def test_edit_back_without_a_newer_edit_date_is_detected_by_text(tmp_path: Path) -> None:
    edit_date = NOW - timedelta(hours=5)
    state = build(tmp_path, [m(1, text="A", edit_date=edit_date)])
    [to_b] = await recheck(tmp_path, state, telegram(m(1, text="B", edit_date=edit_date)))
    state = apply(tmp_path, state, [to_b])

    [to_a] = await recheck(tmp_path, state, telegram(m(1, text="A", edit_date=edit_date)))

    assert isinstance(to_a, EditRecord)
    assert to_a.text == "A"


async def test_the_latest_edit_in_the_files_is_the_known_version(tmp_path: Path) -> None:
    first = EditRecord(CHAT_ID, 1, NOW - timedelta(hours=9), NOW, "B", None, DETECTED_EVENT)
    second = EditRecord(CHAT_ID, 1, NOW - timedelta(hours=8), NOW, "C", None, DETECTED_EVENT)
    state = build(tmp_path, [m(1, text="A"), second, first])

    result = await recheck(
        tmp_path, state, telegram(m(1, text="C", edit_date=NOW - timedelta(hours=8)))
    )

    assert result == []


async def test_two_edits_with_the_same_second_resolve_to_the_later_line(tmp_path: Path) -> None:
    when = NOW - timedelta(hours=6)
    first = EditRecord(CHAT_ID, 1, when, NOW, "B", None, DETECTED_EVENT)
    second = EditRecord(CHAT_ID, 1, when, NOW, "C", None, DETECTED_EVENT)
    state = build(tmp_path, [m(1, text="A"), first, second])

    assert await recheck(tmp_path, state, telegram(m(1, text="C", edit_date=when))) == []


async def test_an_older_edit_record_does_not_override_a_newer_message_version(
    tmp_path: Path,
) -> None:
    stale = EditRecord(CHAT_ID, 1, NOW - timedelta(hours=9), NOW, "old", None, DETECTED_EVENT)
    current = m(1, text="newer", edit_date=NOW - timedelta(hours=2))
    state = build(tmp_path, [current, stale])

    assert await recheck(tmp_path, state, telegram(current)) == []


async def test_media_saved_records_do_not_disturb_the_comparison(tmp_path: Path) -> None:
    saved = MediaSavedRecord(CHAT_ID, 1, "2026-10/1.jpg", NOW)
    state = build(tmp_path, [m(1, media=photo()), saved])

    assert await recheck(tmp_path, state, telegram(m(1, media=photo()))) == []


async def test_a_large_history_with_a_few_differences(tmp_path: Path) -> None:
    records = [m(i, 100 + i % 40) for i in range(1, 1501)]
    state = build(tmp_path, records)
    remote = {r.msg_id: r for r in records}
    remote[300] = replace(remote[300], text="changed")
    del remote[900]
    del remote[1200]

    result = await recheck(tmp_path, state, telegram(*remote.values()))

    assert [(type(r).__name__, record_sort_id(r)) for r in result] == [
        ("EditRecord", 300),
        ("DeleteRecord", 1200),
    ]
    delete = result[1]
    assert isinstance(delete, DeleteRecord)
    assert delete.msg_ids == (900, 1200)


async def test_stale_records_in_the_files_are_ignored(tmp_path: Path) -> None:
    long_ago = SINCE - timedelta(seconds=1)
    state = replace(
        build(
            tmp_path,
            [
                m(1, text="below the floor"),
                m(3, text="kept"),
                EditRecord(CHAT_ID, 1, NOW - timedelta(hours=2), NOW, "floored edit", None),
                EditRecord(CHAT_ID, 3, long_ago, NOW, "ancient edit", None, DETECTED_EVENT),
                DeleteRecord(CHAT_ID, (3,), long_ago, DETECTED_EVENT),
                DeleteRecord(CHAT_ID, (5,), NOW - timedelta(hours=1), DETECTED_EVENT),
            ],
            floor_id=2,
        ),
        last_id=5,
    )

    result = await recheck(tmp_path, state, telegram(m(3, text="changed")))

    assert [(type(r).__name__, record_sort_id(r)) for r in result] == [("EditRecord", 3)]
