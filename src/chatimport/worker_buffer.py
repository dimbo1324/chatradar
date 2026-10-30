"""Live events between two flushes: the bounded buffer and the pure event-to-record mapping."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from chatimport.ports import EditedMessageEvent, NewMessageEvent
from chatimport.records import DETECTED_EVENT, DeleteRecord, EditRecord, MessageRecord

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from chatimport.config import EventsConfig, LiveConfig
    from chatimport.ports import ChatEvent
    from chatimport.records import Record
    from chatimport.storage.state import ChatState

MAX_PENDING_EVENTS: Final = 20_000
RECENT_IDS: Final = 10_000


class RecentIds:
    """The last `capacity` message ids this worker wrote, oldest forgotten first."""

    def __init__(self, capacity: int = RECENT_IDS) -> None:
        self._capacity = capacity
        self._order: deque[int] = deque()
        self._ids: set[int] = set()

    def add(self, ids: Iterable[int]) -> None:
        for msg_id in ids:
            if msg_id in self._ids:
                continue
            self._ids.add(msg_id)
            self._order.append(msg_id)
            if len(self._order) > self._capacity:
                self._ids.discard(self._order.popleft())

    def __contains__(self, msg_id: object) -> bool:
        return msg_id in self._ids


def events_to_records(
    events: Sequence[ChatEvent],
    state: ChatState,
    config: EventsConfig,
    *,
    chat_id: int,
    now: datetime,
    recent: RecentIds,
) -> list[Record]:
    """Records for a batch of live events.

    A new message at or below `last_id` is kept unless this worker wrote it recently: it may
    be a late delivery (Telegram fills update gaps out of order). The writer still drops it
    if the month already holds that id.
    """
    records: list[Record] = []
    seen: set[int] = set()
    for event in events:
        if isinstance(event, NewMessageEvent):
            msg_id = event.record.msg_id
            if msg_id <= state.floor_id or msg_id in seen:
                continue
            if msg_id > state.last_id or msg_id not in recent:
                seen.add(msg_id)
                records.append(event.record)
        elif isinstance(event, EditedMessageEvent):
            message = event.record
            if config.track_edits and message.msg_id >= state.floor_id:
                records.append(
                    EditRecord(
                        chat_id=message.chat_id,
                        msg_id=message.msg_id,
                        edit_date=message.edit_date or message.fetched_at,
                        fetched_at=message.fetched_at,
                        text=message.text,
                        media=message.media,
                        detected_by=DETECTED_EVENT,
                    )
                )
        elif config.track_deletes and event.chat_id == chat_id:
            ids = tuple(i for i in event.msg_ids if i >= state.floor_id)
            if ids:
                records.append(
                    DeleteRecord(
                        chat_id=chat_id,
                        msg_ids=ids,
                        fetched_at=now,
                        detected_by=DETECTED_EVENT,
                    )
                )
    return records


def split_late(records: Sequence[Record], last_id: int) -> tuple[list[Record], list[MessageRecord]]:
    """(records to append, messages at or below `last_id` to merge into their month)."""
    append: list[Record] = []
    late: list[MessageRecord] = []
    for record in records:
        if isinstance(record, MessageRecord) and record.msg_id <= last_id:
            late.append(record)
        else:
            append.append(record)
    return append, late


class LiveBuffer:
    """Events waiting for the next flush. Holds at most `capacity` events; anything beyond
    is counted in `dropped`, and the worker then catches up from Telegram instead."""

    def __init__(self, capacity: int = MAX_PENDING_EVENTS) -> None:
        self.capacity = capacity
        self._events: list[ChatEvent] = []
        self._first_at: datetime | None = None
        self._dropped = 0

    def __len__(self) -> int:
        return len(self._events)

    def take(self, event: ChatEvent | None, now: datetime) -> None:
        if event is None:
            return
        if len(self._events) >= self.capacity:
            self._dropped += 1
            return
        if not self._events:
            self._first_at = now
        self._events.append(event)

    def note_dropped(self, count: int = 1) -> None:
        self._dropped += count

    def take_dropped(self) -> int:
        dropped, self._dropped = self._dropped, 0
        return dropped

    def deadline(self, live: LiveConfig) -> datetime | None:
        if self._first_at is None:
            return None
        return self._first_at + timedelta(seconds=live.flush_every_seconds)

    def due(self, now: datetime, live: LiveConfig) -> bool:
        if not self._events:
            return False
        deadline = self.deadline(live)
        return len(self._events) >= live.flush_every_messages or (
            deadline is not None and now >= deadline
        )

    def pop_all(self) -> list[ChatEvent]:
        events, self._events = self._events, []
        self._first_at = None
        return events

    def requeue(self, events: list[ChatEvent], now: datetime) -> None:
        """Put back events whose write failed, ahead of newer ones; the oldest overflow is
        dropped and counted."""
        merged = events + self._events
        excess = len(merged) - self.capacity
        if excess > 0:
            self._dropped += excess
            merged = merged[excess:]
        self._events = merged
        self._first_at = now if merged else None
