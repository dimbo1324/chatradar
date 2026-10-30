"""Live intake of one chat: the event queue, the buffer between flushes, and the flush that
turns buffered events into records on disk."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from chatimport.records import MessageRecord
from chatimport.worker_buffer import LiveBuffer, RecentIds, events_to_records

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from chatimport.config import EventsConfig
    from chatimport.ports import ChatEvent, Clock
    from chatimport.records import Record
    from chatimport.storage.state import ChatState
    from chatimport.worker_store import WorkerStore

log = logging.getLogger(__name__)


class LiveIntake:
    def __init__(
        self,
        *,
        chat_id: int,
        title: str,
        store: WorkerStore,
        lock: asyncio.Lock,
        events: EventsConfig,
        clock: Clock,
    ) -> None:
        self._chat_id = chat_id
        self._title = title
        self._store = store
        self._lock = lock
        self._events = events
        self._clock = clock
        self.queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
        self.buffer = LiveBuffer()
        self.recent = RecentIds()
        self._state_suspect = False

    def submit(self, event: ChatEvent) -> None:
        """Never blocks; beyond the buffer's capacity the event is only counted."""
        if self.queue.qsize() >= self.buffer.capacity:
            self.buffer.note_dropped()
            return
        self.queue.put_nowait(event)

    def wake(self) -> None:
        self.queue.put_nowait(None)

    def drain(self) -> None:
        while not self.queue.empty():
            self.buffer.take(self.queue.get_nowait(), self._clock.now())

    async def wait(self, until: datetime) -> None:
        """Take events into the buffer until one arrives (or a wake), or `until` passes."""
        timeout = max((until - self._clock.now()).total_seconds(), 0.0)
        try:
            event = await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            event = None
        self.buffer.take(event, self._clock.now())
        self.drain()

    async def discard_until(self, until: datetime, keep_waiting: Callable[[], bool]) -> bool:
        """Drop events until `until` passes (True) or `keep_waiting` turns false (False)."""
        while keep_waiting():
            remaining = (until - self._clock.now()).total_seconds()
            if remaining <= 0:
                return True
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.queue.get(), remaining)
        return False

    async def flush(self) -> ChatState | None:
        """Write the buffer; the new state, or None when nothing was flushed."""
        async with self._lock:
            if not len(self.buffer):
                return None
            events = self.buffer.pop_all()
            try:
                state = await self._state_for_flush()
            except BaseException:
                self.buffer.requeue(events, self._clock.now())
                raise
            if state is None:
                log.warning("dropped %s buffered events of chat %s", len(events), self._chat_id)
                return None
            records = events_to_records(
                events,
                state,
                self._events,
                chat_id=self._chat_id,
                now=self._clock.now(),
                recent=self.recent,
            )
            try:
                state = await self.write(state, records)
            except BaseException:
                self._state_suspect = True
                self.buffer.requeue(events, self._clock.now())
                raise
            log.debug("flushed %s records of chat %s", len(records), self._chat_id)
            return state

    async def write(self, state: ChatState, records: list[Record]) -> ChatState:
        """Append, or merge late messages; `state` itself when nothing was written."""
        written = await self._store.write_live(state, records)
        self.recent.add(r.msg_id for r in records if isinstance(r, MessageRecord))
        return written

    async def _state_for_flush(self) -> ChatState | None:
        """The data may have been written before a failed state save: realign from the files."""
        if self._state_suspect and self._store.resolve_folder().is_dir():
            state = await self._store.recover(self._title)
            self._state_suspect = False
            return state
        return self._store.load()
