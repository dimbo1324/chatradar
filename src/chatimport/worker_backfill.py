"""History download of one chat: the newest month (head) and everything older (tail).

Both hold a `BackfillSlots` slot while they talk to Telegram, so only
`backfill.max_parallel_chats` chats download history at once; a paused chat gives its slot
back while it waits.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from chatimport.ports import AccessLost, SessionRevoked
from chatimport.storage.chat_store import StateGone
from chatimport.storage.layout import month_key
from chatimport.storage.state import (
    PHASE_CATCH_UP,
    PHASE_HEAD_BACKFILL,
    BackfillState,
    StateUnreadable,
    new_state,
)
from chatimport.worker_signals import Refetch, Stop

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime

    from chatimport.config import BackfillConfig
    from chatimport.ports import Clock, TelegramGateway
    from chatimport.records import MessageRecord
    from chatimport.runtime import BackfillSlots, TrackedChat
    from chatimport.storage.state import ChatState
    from chatimport.worker_signals import WorkerSignals
    from chatimport.worker_store import WorkerStore

log = logging.getLogger(__name__)

TAIL_FLUSH_RECORDS: Final = 20_000
RETRY_FIRST_SECONDS: Final = 60.0
RETRY_MAX_SECONDS: Final = 3600.0


class SlotHolder:
    """One chat's claim on the shared backfill slots, which it can give back and retake."""

    def __init__(self, slots: BackfillSlots | None, chat_id: int) -> None:
        self._slots = slots
        self._chat_id = chat_id
        self._context: AbstractAsyncContextManager[None] | None = None

    @property
    def held(self) -> bool:
        return self._context is not None

    async def acquire(self) -> None:
        if self._slots is None or self._context is not None:
            return
        context = self._slots.acquire(self._chat_id)
        await context.__aenter__()
        self._context = context

    async def release(self) -> None:
        context, self._context = self._context, None
        if context is not None:
            await context.__aexit__(None, None, None)

    @contextlib.asynccontextmanager
    async def holding(self) -> AsyncGenerator[None]:
        await self.acquire()
        try:
            yield
        finally:
            await self.release()

    @contextlib.asynccontextmanager
    async def suspended(self) -> AsyncGenerator[None]:
        """Give the slot back for the body; take it again only if the body ends normally
        (a stop must not wait for a slot)."""
        held = self.held
        await self.release()
        yield
        if held:
            await self.acquire()


@dataclass(frozen=True, slots=True)
class NewestMonth:
    head_id: int
    month: str | None = None
    records: list[MessageRecord] = field(default_factory=list["MessageRecord"])


async def collect_newest_month(
    gateway: TelegramGateway,
    chat_id: int,
    *,
    batch_size: int,
    between_batches: Callable[[], Awaitable[None]],
) -> NewestMonth:
    """The chat's newest message id and every message of the month that message is in."""
    head_id = await gateway.newest_id(chat_id)
    if not head_id:
        return NewestMonth(head_id)
    records: list[MessageRecord] = []
    month: str | None = None
    async for record in gateway.iter_history(chat_id):
        key = month_key(record.date)
        if month is None:
            month = key
        elif key < month:
            break
        records.append(record)
        if len(records) % batch_size == 0:
            await between_batches()
    return NewestMonth(head_id, month, records) if records else NewestMonth(head_id)


async def head_start_state(store: WorkerStore, chat: TrackedChat, now: datetime) -> ChatState:
    """The state a head backfill starts from. An empty folder gets a fresh state; over
    existing parts (a refetch while the folder is still there) the parts and their history
    stay, and only the floor and the backfill progress start over."""
    backfill = BackfillState(started_at=now)
    if store.has_parts():
        state = await store.recover(chat.title)
        return replace(
            state, phase=PHASE_HEAD_BACKFILL, floor_id=0, floor_reason=None, backfill=backfill
        )
    return replace(new_state(chat.chat_id, chat.title, chat.username, now), backfill=backfill)


def head_done_state(state: ChatState, newest: NewestMonth, now: datetime) -> ChatState:
    """`state` after the newest month is downloaded (the caller writes the month)."""
    if newest.month is None:
        backfill = BackfillState(done=True, head_id=newest.head_id, started_at=now)
        last_id = max(state.last_id, newest.head_id)
    else:
        ids = [record.msg_id for record in newest.records]
        backfill = BackfillState(
            done=False, head_id=newest.head_id, oldest_done_id=min(ids), started_at=now
        )
        last_id = max(state.last_id, *ids)
    return replace(state, phase=PHASE_CATCH_UP, last_id=last_id, backfill=backfill)


class TailBackfill:
    """Downloads history below `backfill.oldest_done_id`, month by month, newest first, down
    to `floor_id`, merging into parts that may already exist. Every write reloads
    `state.json` under the chat lock, so a floor or `done` set by another component (trim,
    disk guard, `backfill --deeper`) is never overwritten."""

    def __init__(
        self,
        *,
        chat_id: int,
        store: WorkerStore,
        gateway: TelegramGateway,
        config: BackfillConfig,
        clock: Clock,
        lock: asyncio.Lock,
        signals: WorkerSignals,
        slot: SlotHolder,
        adopt: Callable[[ChatState], None],
    ) -> None:
        self._chat_id = chat_id
        self._store = store
        self._gateway = gateway
        self._config = config
        self._clock = clock
        self._lock = lock
        self._signals = signals
        self._slot = slot
        self._adopt = adopt

    async def run(self) -> None:
        while True:
            state = self._store.load()
            if state is None:
                raise StateGone(f"state of chat {self._chat_id} is gone")
            if state.backfill.done:
                return
            offset = state.backfill.oldest_done_id or state.floor_id
            floor = state.floor_id
            if not (floor and floor >= offset):
                async with self._slot.holding():
                    await self._walk(offset, floor)
            if await self._finish(floor):
                return

    async def _walk(self, offset: int, floor: int) -> None:
        month: str | None = None
        pending: list[MessageRecord] = []
        seen = 0
        async for record in self._gateway.iter_history(
            self._chat_id, offset_id=offset, min_id=floor
        ):
            await self._gate()
            key = month_key(record.date)
            if month is not None and key < month and pending:
                await self._write(month, pending)
                pending = []
            if month is None or key < month:
                month = key
            pending.append(record)
            if len(pending) >= TAIL_FLUSH_RECORDS:
                await self._write(month, pending)
                pending = []
            seen += 1
            if seen % self._config.batch_size == 0:
                await self._clock.sleep(self._config.pause_between_requests_sec)
        if month is not None and pending:
            await self._write(month, pending)

    async def _gate(self) -> None:
        if self._signals.backfill_open:
            return
        async with self._slot.suspended():
            await self._signals.wait_backfill_gate()

    async def _write(self, month: str, records: list[MessageRecord]) -> None:
        async with self._lock:
            state = self._store.require()
            kept = [r for r in records if r.msg_id > state.floor_id]
            previous = state.backfill.oldest_done_id
            oldest = min(r.msg_id for r in records)
            state = replace(
                state,
                backfill=replace(state.backfill, oldest_done_id=min(oldest, previous or oldest)),
            )
            written = await self._store.merge_month(state, month, kept) if kept else state
            if written is state:
                written = self._store.save(state)
            self._adopt(written)
        log.info("tail month %s of chat %s: %s messages", month, self._chat_id, len(kept))

    async def _finish(self, walked_to: int) -> bool:
        """Mark the backfill done, unless the floor was lowered below where this walk
        stopped (`backfill --deeper` while it ran): then another walk is needed."""
        async with self._lock:
            state = self._store.require()
            if state.backfill.done:
                return True
            if state.floor_id < walked_to:
                return False
            state = self._store.save(replace(state, backfill=replace(state.backfill, done=True)))
            self._adopt(state)
        log.info("backfill of chat %s is complete", self._chat_id)
        return True


class TailTask:
    """Runs the tail in the background beside the live loop. Errors that concern the whole
    chat (lost access, a revoked session, a missing or unreadable state) are handed to the
    live loop through `take_error`. Any other failure stays here: the tail alone retries
    with a growing delay, and `failure` names it for the status."""

    def __init__(
        self,
        tail: TailBackfill,
        *,
        chat_id: int,
        clock: Clock,
        guard: Callable[[Callable[[], Awaitable[None]]], Awaitable[None]],
        wake: Callable[[], None],
    ) -> None:
        self._tail = tail
        self._chat_id = chat_id
        self._clock = clock
        self._guard = guard
        self._wake = wake
        self.failure: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._error: Exception | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def take_error(self) -> Exception | None:
        error, self._error = self._error, None
        if error is not None:
            self._task = None
        return error

    async def cancel(self) -> None:
        task, self._task = self._task, None
        self._error = None
        self.failure = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def _run(self) -> None:
        delay = RETRY_FIRST_SECONDS
        while True:
            try:
                await self._guard(self._tail.run)
            except Stop, Refetch:
                return
            except (AccessLost, SessionRevoked, StateGone, StateUnreadable) as error:
                self._error = error
                self._wake()
                return
            except Exception as error:
                self.failure = f"tail: {type(error).__name__}"
                log.warning(
                    "tail backfill of chat %s failed (%s); retrying in %s s",
                    self._chat_id,
                    type(error).__name__,
                    delay,
                )
                await self._clock.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_SECONDS)
                continue
            self.failure = None
            self._wake()
            return
