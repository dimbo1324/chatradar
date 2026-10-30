"""The worker's view of its chat folder. Heavy file work (a month rewrite, a recover, a big
append) runs in a thread, so it never stalls the event loop (Telethon, the other chats);
reading or saving the small `state.json` and a live batch stay on the loop."""

from __future__ import annotations

import asyncio
import contextlib
from functools import partial
from itertools import groupby
from typing import TYPE_CHECKING, Final

from chatimport.storage.layout import list_parts, month_key
from chatimport.worker_buffer import split_late

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime
    from pathlib import Path

    from chatimport.records import MessageRecord, Record
    from chatimport.storage.chat_store import ChatStore
    from chatimport.storage.state import ChatState

INLINE_APPEND_RECORDS: Final = 100


async def run_blocking[T](call: Callable[[], T]) -> T:
    """Run `call` in a thread. A cancelled caller still waits for the thread to end, so a
    chat lock held around this call is never released while the thread writes."""
    future = asyncio.ensure_future(asyncio.to_thread(call))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait({future})
        future.exception()
        raise


class WorkerStore:
    def __init__(self, store: ChatStore) -> None:
        self._store = store

    @property
    def folder(self) -> Path:
        return self._store.folder

    def resolve_folder(self) -> Path:
        return self._store.resolve_folder()

    def load(self) -> ChatState | None:
        return self._store.load()

    def require(self) -> ChatState:
        return self._store.require()

    def has_parts(self) -> bool:
        return bool(list_parts(self._store.resolve_folder()))

    def save(self, state: ChatState) -> ChatState:
        return self._store.save(state)

    def oldest_message_date(self, state: ChatState) -> datetime | None:
        """Reads only up to the first message of the oldest part."""
        return self._store.oldest_message_date(state)

    async def append(self, state: ChatState, records: Sequence[Record]) -> ChatState:
        if len(records) < INLINE_APPEND_RECORDS:
            return self._store.append(state, records)
        return await run_blocking(partial(self._store.append, state, records))

    async def merge_month(
        self, state: ChatState, month: str, messages: Sequence[MessageRecord]
    ) -> ChatState:
        """Like `ChatStore.merge_month`, which returns `state` unsaved when every message is
        already stored."""
        return await run_blocking(partial(self._store.merge_month, state, month, messages))

    async def write_live(self, state: ChatState, records: Sequence[Record]) -> ChatState:
        """Append new records; merge messages at or below `last_id` (late deliveries, recheck
        gap fills) into their month in `msg_id` order, where ids already stored are dropped.
        Returns `state` itself when nothing was written."""
        append, late = split_late(records, state.last_id)
        if append:
            state = await self.append(state, append)
        late.sort(key=lambda r: month_key(r.date))
        for month, group in groupby(late, key=lambda r: month_key(r.date)):
            state = await self.merge_month(state, month, list(group))
        return state

    async def recover(self, title: str) -> ChatState:
        return await run_blocking(partial(self._store.recover, title=title))


class OldestDate:
    """Date of the chat's oldest stored message, re-read only when the oldest part changes
    (a trim or a recover by another component)."""

    def __init__(self, store: WorkerStore) -> None:
        self._store = store
        self.value: datetime | None = None
        self._key: str | None = None

    def reset(self) -> None:
        self.value = self._key = None

    def refresh(self, state: ChatState) -> None:
        found = self._store.oldest_message_date(state)
        if found is not None:
            self.value = found
            self._key = min(state.chunks)

    def refresh_if_moved(self, state: ChatState) -> None:
        if self.value is not None and state.chunks and min(state.chunks) != self._key:
            self.refresh(state)
