"""The per-chat worker (spec §4, §8): recover or head backfill, catch up, live batches,
background tail backfill, reconcile, recheck. `state.json` is the truth; every change to it
or to the files happens under `lock`, starting with a fresh load. Parts: `worker_signals`
(control flags), `worker_live` and `worker_buffer` (live intake), `worker_backfill` (history
download), `worker_store` (file access, heavy work in threads), `flood` (FloodWait)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol

from chatimport.flood import FloodReporter, retry_on_flood
from chatimport.ports import AccessLost, SessionRevoked
from chatimport.records import MessageRecord
from chatimport.runtime import ChatStatus, Level
from chatimport.storage.chat_store import ChatStore, StateGone
from chatimport.storage.state import (
    PHASE_CATCH_UP,
    PHASE_HEAD_BACKFILL,
    PHASE_LIVE,
    PHASE_NO_ACCESS,
    PHASE_PAUSED,
    PHASE_RECOVER,
    StateUnreadable,
)
from chatimport.worker_backfill import (
    RETRY_FIRST_SECONDS,
    RETRY_MAX_SECONDS,
    SlotHolder,
    TailBackfill,
    TailTask,
    collect_newest_month,
    head_done_state,
    head_start_state,
)
from chatimport.worker_live import LiveIntake
from chatimport.worker_signals import Refetch, Stop, WorkerSignals
from chatimport.worker_store import OldestDate, WorkerStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.config import Config
    from chatimport.ports import ChatEvent, Clock, TelegramGateway
    from chatimport.records import Record
    from chatimport.runtime import BackfillSlots, Notifier, TrackedChat
    from chatimport.storage.state import ChatState

__all__ = ["ChatWorker", "RecheckFn"]

log = logging.getLogger(__name__)

_STOP_GRACE_SECONDS: Final = 5.0
_BYTES_PER_MB: Final = 1024 * 1024


class RecheckFn(Protocol):
    def __call__(
        self,
        gateway: TelegramGateway,
        folder: Path,
        state: ChatState,
        *,
        now: datetime,
        days: int,
        track_edits: bool,
        track_deletes: bool,
    ) -> Awaitable[list[Record]]: ...


class ChatWorker:
    def __init__(
        self,
        chat: TrackedChat,
        *,
        root: Path,
        gateway: TelegramGateway,
        config: Config,
        clock: Clock,
        notifier: Notifier,
        recheck: RecheckFn,
        slots: BackfillSlots | None = None,
    ) -> None:
        self._chat = chat
        self._gateway = gateway
        self._config = config
        self._clock = clock
        self._notifier = notifier
        self._recheck = recheck
        self._on_flood = FloodReporter(chat.chat_id, chat.title, notifier)
        chunk_bytes = config.output.max_chunk_mb * _BYTES_PER_MB
        self._store = WorkerStore(
            ChatStore(
                root, chat.chat_id, chat.folder_name, max_chunk_bytes=chunk_bytes, clock=clock
            )
        )
        self._lock = asyncio.Lock()
        self._intake = LiveIntake(
            chat_id=chat.chat_id,
            title=chat.title,
            store=self._store,
            lock=self._lock,
            events=config.events,
            clock=clock,
        )
        self._signals = WorkerSignals(self._intake.wake)
        self._head_slot = SlotHolder(slots, chat.chat_id)
        self._tail_backfill = TailBackfill(
            chat_id=chat.chat_id,
            store=self._store,
            gateway=gateway,
            config=config.backfill,
            clock=clock,
            lock=self._lock,
            signals=self._signals,
            slot=SlotHolder(slots, chat.chat_id),
            adopt=self._adopt,
        )
        self._tail = TailTask(
            self._tail_backfill,
            chat_id=chat.chat_id,
            clock=clock,
            guard=self._flood,
            wake=self._intake.wake,
        )

        self._state: ChatState | None = None
        self._oldest = OldestDate(self._store)
        self._phase = PHASE_RECOVER
        self._error: str | None = None
        self._recheck_requested = False
        self._recheck_days: int | None = None
        self._access_retry = RETRY_FIRST_SECONDS
        self._exited = asyncio.Event()
        self._exited.set()
        self._run_task: asyncio.Task[None] | None = None

    @property
    def chat_id(self) -> int:
        return self._chat.chat_id

    @property
    def folder(self) -> Path:
        """The chat's folder on disk now (may look it up under the root)."""
        return self._store.resolve_folder()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def submit(self, event: ChatEvent) -> None:
        self._intake.submit(event)

    def pause(self) -> None:
        self._signals.pause()

    def resume(self) -> None:
        self._signals.resume()

    def pause_backfill(self) -> None:
        self._signals.pause_backfill()

    def resume_backfill(self) -> None:
        """Also makes the live loop look at `state.json` again, so a floor lowered by
        `backfill --deeper` starts a tail at once."""
        self._signals.resume_backfill()

    def request_refetch(self) -> None:
        self._signals.request_refetch()

    def request_recheck(self, days: int | None = None) -> None:
        self._recheck_requested = True
        self._recheck_days = days
        self._intake.wake()

    def status(self) -> ChatStatus:
        try:
            state = self._store.load()
        except StateUnreadable:
            state = self._state
        if state is not None:
            self._oldest.refresh_if_moved(state)
        return ChatStatus(
            chat_id=self.chat_id,
            title=self._chat.title,
            phase=state.phase if state is not None else self._phase,
            last_id=state.last_id if state is not None else 0,
            backfill_done=state is not None and state.backfill.done,
            oldest_date=self._oldest.value if state is not None else None,
            records=state.total_records if state is not None else 0,
            paused=self._signals.paused,
            error=self._error or self._tail.failure,
        )

    async def stop(self) -> None:
        self._signals.stop()
        task = self._run_task
        if task is not None and task is not asyncio.current_task():
            _, pending = await asyncio.wait({task}, timeout=_STOP_GRACE_SECONDS)
            if pending:
                task.cancel()
                await self._exited.wait()
        await self._tail.cancel()
        self._intake.drain()
        await self._flush()

    async def run(self) -> None:
        await self._execute(once=False)

    async def sync_once(self) -> None:
        await self._execute(once=True)

    async def _execute(self, *, once: bool) -> None:
        self._exited.clear()
        self._run_task = asyncio.current_task()
        try:
            await self._supervise(once=once)
        except Stop:
            pass
        except SessionRevoked:
            self._error = "session revoked"
            self._notifier.notify(
                Level.ERROR, self._chat.title, "Telegram session revoked: run chatimport login"
            )
            raise
        except Exception as error:
            self._error = type(error).__name__
            raise
        finally:
            self._run_task = None
            await self._tail.cancel()
            try:
                if not once:
                    self._intake.drain()
                await self._flush()
            except Exception:
                log.exception("final flush failed for chat %s", self.chat_id)
            self._exited.set()

    async def _supervise(self, *, once: bool) -> None:
        phase: str | None = None
        while not self._signals.stopping:
            try:
                if phase is None:
                    phase = await self._initial_phase()
                phase = await self._step(phase)
                self._error = None
                self._access_retry = RETRY_FIRST_SECONDS
                if once and phase == PHASE_LIVE:
                    await self._flood(self._tail_backfill.run)
                    return
            except Refetch:
                await self._tail.cancel()
                self._signals.clear_refetch()
                phase = PHASE_HEAD_BACKFILL
            except (StateGone, StateUnreadable) as error:
                log.warning("state of chat %s is not available: %s", self.chat_id, error)
                await self._tail.cancel()
                watch = self._config.watch
                await self._clock.sleep(watch.check_every_seconds * watch.confirm_checks)
                phase = None
            except AccessLost:
                await self._tail.cancel()
                await self._mark_no_access()
                if once:
                    return
                await self._wait_for_access_retry()
                phase = PHASE_HEAD_BACKFILL if self._signals.refetch else None
                self._signals.clear_refetch()

    async def _step(self, phase: str) -> str:
        if phase == PHASE_HEAD_BACKFILL:
            await self._flood(self._head_backfill)
            return PHASE_CATCH_UP
        if phase == PHASE_LIVE:
            return await self._live()
        await self._flood(self._catch_up)
        return PHASE_LIVE

    async def _initial_phase(self) -> str:
        if not self._store.resolve_folder().is_dir():
            return PHASE_HEAD_BACKFILL
        async with self._lock:
            state = await self._store.recover(self._chat.title)
            self._adopt(state)
        log.info("recovered chat %s: last_id=%s", self.chat_id, state.last_id)
        if state.phase == PHASE_PAUSED:
            self._signals.restore_pause()
        if state.last_id == 0 and not state.chunks and not state.backfill.done:
            return PHASE_HEAD_BACKFILL
        return PHASE_CATCH_UP

    async def _head_backfill(self) -> None:
        now = self._clock.now()
        self._signals.clear_refetch()
        async with self._lock:
            state = await head_start_state(self._store, self._chat, now)
            self._state = self._store.save(state)
            self._oldest.reset()
        self._phase = PHASE_HEAD_BACKFILL
        await self._checkpoint()

        async with self._head_slot.holding():
            newest = await collect_newest_month(
                self._gateway,
                self.chat_id,
                batch_size=self._config.backfill.batch_size,
                between_batches=self._pause_between_requests,
            )

        async with self._lock:
            state = head_done_state(self._store.require(), newest, now)
            if newest.month is None:
                state = self._store.save(state)
            else:
                written = await self._store.merge_month(state, newest.month, newest.records)
                state = written if written is not state else self._store.save(state)
                self._intake.recent.add(r.msg_id for r in newest.records)
            self._adopt(state)
        self._phase = PHASE_CATCH_UP
        log.info("head backfill of chat %s: %s messages", self.chat_id, len(newest.records))

    async def _catch_up(self) -> None:
        self._phase = PHASE_CATCH_UP
        await self._checkpoint()
        await self._set_phase(PHASE_CATCH_UP)
        state = self._store.require()
        batch: list[MessageRecord] = []
        batch_size = self._config.backfill.batch_size
        async for record in self._gateway.iter_since(self.chat_id, state.last_id):
            batch.append(record)
            if len(batch) >= batch_size:
                await self._write_batch(batch)
                batch = []
                await self._pause_between_requests()
        await self._write_batch(batch)

    async def _write_batch(self, records: list[MessageRecord]) -> None:
        if not records:
            return
        async with self._lock:
            state = self._store.require()
            fresh = [r for r in records if r.msg_id > state.last_id and r.msg_id > state.floor_id]
            if fresh:
                self._state = await self._store.append(state, fresh)
                self._intake.recent.add(r.msg_id for r in fresh)
        if self._oldest.value is None and self._state is not None:
            self._oldest.refresh(self._state)

    async def _live(self) -> str:
        await self._set_phase(PHASE_LIVE)
        await self._ensure_tail(reload=False)
        live = self._config.live
        buffer = self._intake.buffer
        next_reconcile = self._clock.now() + timedelta(minutes=live.reconcile_every_minutes)
        while True:
            self._signals.raise_if_interrupted()
            if self._signals.paused:
                await self._park()
                return PHASE_CATCH_UP
            if (error := self._tail.take_error()) is not None:
                raise error
            if self._signals.take_tail_check():
                await self._ensure_tail(reload=True)
            if self._recheck_requested and self._backfill_finished():
                await self._do_recheck()

            flush_at = buffer.deadline(live)
            await self._intake.wait(min(next_reconcile, flush_at or next_reconcile))

            now = self._clock.now()
            if dropped := buffer.take_dropped():
                log.warning(
                    "dropped %s live events of chat %s; catching up instead", dropped, self.chat_id
                )
                self._recheck_requested = True
                await self._flush()
                return PHASE_CATCH_UP
            if buffer.due(now, live):
                await self._flush()
            if now >= next_reconcile:
                await self._flush()
                return PHASE_CATCH_UP

    def _backfill_finished(self) -> bool:
        state = self._state or self._store.load()
        return state is not None and state.backfill.done

    async def _flush(self) -> None:
        state = await self._intake.flush()
        if state is not None:
            self._state = state

    async def _do_recheck(self) -> None:
        days = self._recheck_days or self._config.recheck.days
        self._recheck_requested = False
        self._recheck_days = None
        await self._flush()
        state = self._store.require()
        folder = self._store.folder
        found = await self._flood(
            lambda: self._recheck(
                self._gateway,
                folder,
                state,
                now=self._clock.now(),
                days=days,
                track_edits=self._config.events.track_edits,
                track_deletes=self._config.events.track_deletes,
            )
        )
        async with self._lock:
            state = replace(self._store.require(), last_recheck_at=self._clock.now())
            records = [
                r
                for r in found
                if not (isinstance(r, MessageRecord) and r.msg_id <= state.floor_id)
            ]
            written = await self._intake.write(state, records)
            self._state = written if written is not state else self._store.save(state)
        log.info("recheck of chat %s: %s records", self.chat_id, len(records))

    async def _ensure_tail(self, *, reload: bool) -> None:
        if self._tail.running:
            return
        state = self._store.load() if reload or self._state is None else self._state
        if state is not None and not state.backfill.done:
            self._tail.start()

    async def _checkpoint(self) -> None:
        self._signals.raise_if_interrupted()
        if self._signals.paused:
            async with self._head_slot.suspended():
                await self._park()
            self._signals.raise_if_interrupted()

    async def _pause_between_requests(self) -> None:
        await self._clock.sleep(self._config.backfill.pause_between_requests_sec)
        await self._checkpoint()

    async def _park(self) -> None:
        """Wait for `resume`. A stop while parked keeps `paused` in `state.json`, so the
        next start stays paused too."""
        await self._flush()
        previous = self._phase
        await self._persist_phase(PHASE_PAUSED)
        await self._signals.resumed.wait()
        self._signals.raise_if_interrupted()
        await self._persist_phase(previous)

    async def _set_phase(self, phase: str) -> None:
        self._phase = phase
        await self._persist_phase(phase)

    async def _persist_phase(self, phase: str) -> None:
        async with self._lock:
            state = self._store.require()
            if state.phase != phase:
                state = self._store.save(replace(state, phase=phase))
            self._state = state

    async def _mark_no_access(self) -> None:
        self._phase = PHASE_NO_ACCESS
        async with self._lock:
            try:
                state = self._store.load()
            except StateUnreadable:
                state = None
            if state is not None:
                self._state = self._store.save(replace(state, phase=PHASE_NO_ACCESS))
        self._error = "no access"
        self._notifier.notify(Level.ERROR, self._chat.title, "No access to the chat; data kept")
        log.error("no access to chat %s", self.chat_id)

    async def _wait_for_access_retry(self) -> None:
        """Drop live events until a stop, a refetch or the next access retry; the delay
        doubles each time, up to an hour."""
        retry_at = self._clock.now() + timedelta(seconds=self._access_retry)
        self._access_retry = min(self._access_retry * 2, RETRY_MAX_SECONDS)
        signals = self._signals
        if await self._intake.discard_until(
            retry_at, lambda: not (signals.stopping or signals.refetch)
        ):
            log.info("retrying access to chat %s", self.chat_id)

    async def _flood[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        return await retry_on_flood(operation, clock=self._clock, on_wait=self._on_flood)

    def _adopt(self, state: ChatState) -> None:
        self._state = state
        self._oldest.refresh(state)
