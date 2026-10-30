"""The live buffer and the pure mapping from live events to records."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from chatimport.config import EventsConfig, LiveConfig
from chatimport.ports import NewMessageEvent
from chatimport.records import DETECTED_EVENT, DeleteRecord, EditRecord, MessageRecord
from chatimport.storage.state import new_state
from chatimport.worker_buffer import LiveBuffer, RecentIds, events_to_records, split_late
from tests.fakes import CHAT_ID, NOW, msg
from tests.unit.worker.rig import delete_event, edit_event, new_event

if TYPE_CHECKING:
    from chatimport.ports import ChatEvent
    from chatimport.records import Record

STATE = replace(new_state(CHAT_ID, "t", None, NOW), last_id=100, floor_id=10)


def kinds(records: list[Record]) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for record in records:
        if isinstance(record, MessageRecord):
            out.append(("message", record.msg_id))
        elif isinstance(record, EditRecord):
            out.append(("edit", record.msg_id))
        elif isinstance(record, DeleteRecord):
            out.append(("delete", record.msg_ids))
    return out


@pytest.mark.parametrize(
    ("events", "recent", "config", "expected"),
    [
        pytest.param([new_event(101)], [], EventsConfig(), [("message", 101)], id="new"),
        pytest.param(
            [new_event(101), new_event(101)],
            [],
            EventsConfig(),
            [("message", 101)],
            id="duplicate-in-batch",
        ),
        pytest.param([new_event(10)], [], EventsConfig(), [], id="at-floor"),
        pytest.param([new_event(5)], [], EventsConfig(), [], id="below-floor"),
        pytest.param([new_event(99)], [], EventsConfig(), [("message", 99)], id="late-unknown"),
        pytest.param([new_event(99)], [99], EventsConfig(), [], id="late-recently-written"),
        pytest.param([new_event(100)], [100], EventsConfig(), [], id="last-id-replay"),
        pytest.param([edit_event(10, "x")], [], EventsConfig(), [("edit", 10)], id="edit-at-floor"),
        pytest.param([edit_event(9, "x")], [], EventsConfig(), [], id="edit-below-floor"),
        pytest.param(
            [edit_event(50, "x")], [], EventsConfig(track_edits=False), [], id="edits-off"
        ),
        pytest.param(
            [delete_event([5, 10, 50])],
            [],
            EventsConfig(),
            [("delete", (10, 50))],
            id="delete-trimmed-to-floor",
        ),
        pytest.param([delete_event([5])], [], EventsConfig(), [], id="delete-only-below-floor"),
        pytest.param(
            [delete_event([50])], [], EventsConfig(track_deletes=False), [], id="deletes-off"
        ),
        pytest.param(
            [delete_event([50], CHAT_ID + 1)], [], EventsConfig(), [], id="foreign-chat-delete"
        ),
        pytest.param([delete_event([50], None)], [], EventsConfig(), [], id="delete-without-chat"),
    ],
)
def test_events_to_records(
    events: list[ChatEvent],
    recent: list[int],
    config: EventsConfig,
    expected: list[tuple[str, object]],
) -> None:
    known = RecentIds()
    known.add(recent)

    records = events_to_records(events, STATE, config, chat_id=CHAT_ID, now=NOW, recent=known)

    assert kinds(records) == expected


def test_mapped_edits_and_deletes_carry_their_dates_and_source() -> None:
    later = NOW + timedelta(hours=2)
    records = events_to_records(
        [edit_event(50, "new", later), delete_event([60])],
        STATE,
        EventsConfig(),
        chat_id=CHAT_ID,
        now=later,
        recent=RecentIds(),
    )

    edit, delete = records
    assert isinstance(edit, EditRecord)
    assert isinstance(delete, DeleteRecord)
    assert (edit.edit_date, edit.text, edit.detected_by) == (later, "new", DETECTED_EVENT)
    assert (delete.fetched_at, delete.detected_by) == (later, DETECTED_EVENT)


def test_split_late_separates_messages_at_or_below_last_id() -> None:
    edit = EditRecord(CHAT_ID, 5, NOW, NOW, "x", None)
    append, late = split_late([msg(99), msg(100), msg(101), edit], 100)

    assert [getattr(r, "msg_id", None) for r in append] == [101, 5]
    assert [r.msg_id for r in late] == [99, 100]


def test_recent_ids_forget_the_oldest_beyond_capacity() -> None:
    recent = RecentIds(capacity=3)
    recent.add([1, 2, 2, 3])
    recent.add([4])

    assert [i in recent for i in (1, 2, 3, 4)] == [False, True, True, True]


def test_buffer_flushes_by_count_or_by_time_from_the_first_event() -> None:
    live = LiveConfig(flush_every_messages=3, flush_every_seconds=30)
    buffer = LiveBuffer(capacity=10)
    assert buffer.deadline(live) is None
    assert not buffer.due(NOW, live)

    buffer.take(None, NOW)
    buffer.take(new_event(1), NOW)
    buffer.take(new_event(2), NOW + timedelta(seconds=20))

    assert buffer.deadline(live) == NOW + timedelta(seconds=30)
    assert not buffer.due(NOW + timedelta(seconds=29), live)
    assert buffer.due(NOW + timedelta(seconds=30), live)
    buffer.take(new_event(3), NOW)
    assert buffer.due(NOW, live)
    assert len(buffer.pop_all()) == 3
    assert len(buffer) == 0
    assert buffer.deadline(live) is None


def test_buffer_counts_what_it_cannot_hold() -> None:
    buffer = LiveBuffer(capacity=2)
    for i in range(5):
        buffer.take(new_event(i + 1), NOW)
    buffer.note_dropped(4)

    assert len(buffer) == 2
    assert buffer.take_dropped() == 7
    assert buffer.take_dropped() == 0


def test_requeued_events_go_first_and_the_oldest_overflow_is_dropped() -> None:
    buffer = LiveBuffer(capacity=3)
    buffer.take(new_event(10), NOW)
    failed: list[ChatEvent] = [new_event(1), new_event(2), new_event(3)]

    buffer.requeue(failed, NOW + timedelta(seconds=5))

    kept = buffer.pop_all()
    assert [e.record.msg_id for e in kept if isinstance(e, NewMessageEvent)] == [2, 3, 10]
    assert buffer.take_dropped() == 1
    buffer.requeue([], NOW)
    assert buffer.deadline(LiveConfig()) is None
