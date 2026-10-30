"""The per-chat worker (spec §4, §8): recover or head backfill, catch up, live batches,
background tail backfill, reconcile, recheck. `state.json` is the truth; every change to it
or to the files happens under `lock`, starting with a fresh `load_state`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol

from chatimport.ports import (
    AccessLost,
    EditedMessageEvent,
    FloodWait,
    NewMessageEvent,
    SessionRevoked,
)
from chatimport.records import (
    DETECTED_EVENT,
    DeleteRecord,
    EditRecord,
    MessageRecord,
    Record,
)
from chatimport.runtime import ChatStatus, Level
from chatimport.storage.layout import STATE_FILE, find_chat_folder, month_key
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import (
    PHASE_CATCH_UP,
    PHASE_HEAD_BACKFILL,
    PHASE_LIVE,
    PHASE_NO_ACCESS,
    PHASE_PAUSED,
    PHASE_RECOVER,
    BackfillState,
    ChatState,
    load_state,
    new_state,
)
from chatimport.storage.writer import ChunkWriter, iter_part_records

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.config import Config
    from chatimport.ports import ChatEvent, Clock, TelegramGateway
    from chatimport.runtime import Notifier, TrackedChat

log = logging.getLogger(__name__)

_POLL_SECONDS: Final = 1.0
_LONG_FLOOD_SECONDS: Final = 600
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


class _Stop(Exception):
    """The worker was asked to stop."""


class _Refetch(Exception):
    """The chat folder was deleted: start again from the head backfill."""


class _StateGone(Exception):
    """`state.json` vanished under a running operation."""


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
    ) -> None:
        self._chat = chat
        self._root = root
        self._gateway = gateway
        self._config = config
        self._clock = clock
        self._notifier = notifier
        self._recheck = recheck

        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue()
        self._buffer: list[ChatEvent] = []
        self._first_buffered_at: datetime | None = None
        self._state_suspect = False

        self._cached_folder: Path | None = None
        self._state: ChatState | None = None
        self._oldest_date: datetime | None = None
        self._phase = PHASE_RECOVER
        self._error: str | None = None

        self._stopping = False
        self._paused = False
        self._backfill_paused = False
        self._refetch = False
        self._recheck_requested = False
        self._recheck_days: int | None = None
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._backfill_gate = asyncio.Event()
        self._backfill_gate.set()
        self._exited = asyncio.Event()
        self._exited.set()
        self._run_task: asyncio.Task[None] | None = None
        self._tail_task: asyncio.Task[None] | None = None
        self._tail_error: Exception | None = None

    @property
    def chat_id(self) -> int:
        return self._chat.chat_id

    @property
    def folder(self) -> Path:
        cached = self._cached_folder
        if cached is not None and (cached / STATE_FILE).is_file():
            return cached
        found = find_chat_folder(self._root, self.chat_id)
        if found is not None:
            self._cached_folder = found
            return found
        self._cached_folder = None
        return self._root / self._chat.folder_name

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def submit(self, event: ChatEvent) -> None:
        self._queue.put_nowait(event)

    def pause(self) -> None:
        self._paused = True
        self._resumed.clear()
        self._update_gate()
        self._wake()

    def resume(self) -> None:
        self._paused = False
        self._resumed.set()
        self._update_gate()
        self._wake()

    def pause_backfill(self) -> None:
        self._backfill_paused = True
        self._update_gate()

    def resume_backfill(self) -> None:
        self._backfill_paused = False
        self._update_gate()

    def request_refetch(self) -> None:
        self._refetch = True
        self._update_gate()
        self._wake()

    def request_recheck(self, days: int | None = None) -> None:
        self._recheck_requested = True
        self._recheck_days = days
        self._wake()

    def status(self) -> ChatStatus:
        state = self._state or load_state(self.folder)
        if state is None:
            return ChatStatus(
                chat_id=self.chat_id,
                title=self._chat.title,
                phase=self._phase,
                last_id=0,
                backfill_done=False,
                oldest_date=None,
                records=0,
                paused=self._paused,
                error=self._error,
            )
        return ChatStatus(
            chat_id=self.chat_id,
            title=self._chat.title,
            phase=state.phase,
            last_id=state.last_id,
            backfill_done=state.backfill.done,
            oldest_date=self._oldest_date,
            records=sum(info.records for info in state.chunks.values()),
            paused=self._paused,
            error=self._error,
        )

    async def stop(self) -> None:
        self._stopping = True
        self._resumed.set()
        self._update_gate()
        self._wake()
        task = self._run_task
        if task is not None and task is not asyncio.current_task():
            _, pending = await asyncio.wait({task}, timeout=_STOP_GRACE_SECONDS)
            if pending:
                task.cancel()
                await self._exited.wait()
        await self._cancel_tail()
        self._drain_queue()
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
        except _Stop:
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
            await self._cancel_tail()
            try:
                if not once:
                    self._drain_queue()
                await self._flush()
            except Exception:
                log.exception("final flush failed for chat %s", self.chat_id)
            self._exited.set()

    async def _supervise(self, *, once: bool) -> None:
        phase: str | None = None
        while not self._stopping:
            try:
                if phase is None:
                    phase = await self._initial_phase()
                phase = await self._step(phase)
                self._error = None
                if once and phase == PHASE_LIVE:
                    await self._flood(self._tail_backfill)
                    return
            except _Refetch:
                await self._cancel_tail()
                self._refetch = False
                self._update_gate()
                phase = PHASE_HEAD_BACKFILL
            except _StateGone:
                log.warning("state.json is gone for chat %s", self.chat_id)
                await self._cancel_tail()
                watch = self._config.watch
                await self._clock.sleep(watch.check_every_seconds * watch.confirm_checks)
                phase = None
            except AccessLost:
                await self._cancel_tail()
                await self._mark_no_access()
                if once:
                    return
                await self._discard_events_until_stop_or_refetch()
                phase = PHASE_HEAD_BACKFILL if self._refetch else None
                self._refetch = False
                self._update_gate()

    async def _step(self, phase: str) -> str:
        if phase == PHASE_HEAD_BACKFILL:
            await self._flood(self._head_backfill)
            return PHASE_CATCH_UP
        if phase == PHASE_LIVE:
            return await self._live()
        await self._flood(self._catch_up)
        return PHASE_LIVE

    async def _initial_phase(self) -> str:
        folder = self.folder
        if not folder.is_dir():
            return PHASE_HEAD_BACKFILL
        async with self._lock:
            state = recover_chat(
                folder,
                now=self._clock.now(),
                fallback_chat_id=self.chat_id,
                fallback_title=self._chat.title,
            )
            self._state = state
        self._refresh_oldest(state)
        log.info("recovered chat %s: last_id=%s", self.chat_id, state.last_id)
        if state.last_id == 0 and not state.chunks and not state.backfill.done:
            return PHASE_HEAD_BACKFILL
        return PHASE_CATCH_UP

    async def _head_backfill(self) -> None:
        now = self._clock.now()
        async with self._lock:
            state = new_state(self.chat_id, self._chat.title, self._chat.username, now)
            state = replace(state, backfill=BackfillState(started_at=now))
            self._state = self._writer().update_state(state)
            self._oldest_date = None
        self._phase = PHASE_HEAD_BACKFILL
        await self._checkpoint()

        head_id = await self._gateway.newest_id(self.chat_id)
        records: list[MessageRecord] = []
        month: str | None = None
        if head_id:
            async for record in self._gateway.iter_history(self.chat_id):
                key = month_key(record.date)
                if month is None:
                    month = key
                elif key < month:
                    break
                records.append(record)
                if len(records) % self._config.backfill.batch_size == 0:
                    await self._pause_between_requests()

        async with self._lock:
            state = self._require_state()
            if month is None or not records:
                state = replace(
                    state,
                    phase=PHASE_CATCH_UP,
                    last_id=head_id,
                    backfill=BackfillState(done=True, head_id=head_id, started_at=now),
                )
                self._state = self._writer().update_state(state)
            else:
                ids = [record.msg_id for record in records]
                state = replace(
                    state,
                    phase=PHASE_CATCH_UP,
                    last_id=max(ids),
                    backfill=BackfillState(
                        done=False, head_id=head_id, oldest_done_id=min(ids), started_at=now
                    ),
                )
                self._state = self._writer().write_month(state, month, records)
        self._phase = PHASE_CATCH_UP
        self._refresh_oldest(self._state)
        log.info("head backfill of chat %s: %s messages", self.chat_id, len(records))

    async def _catch_up(self) -> None:
        await self._set_phase(PHASE_CATCH_UP)
        state = self._require_state()
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
            state = self._require_state()
            fresh = [r for r in records if r.msg_id > state.last_id and r.msg_id > state.floor_id]
            if fresh:
                self._state = self._writer().append(state, fresh)
        if self._oldest_date is None:
            self._refresh_oldest(self._state)

    async def _live(self) -> str:
        await self._set_phase(PHASE_LIVE)
        self._ensure_tail()
        reconcile_every = self._config.live.reconcile_every_minutes * 60
        next_reconcile = self._seconds_from_now(reconcile_every)
        live = self._config.live
        while True:
            self._raise_if_interrupted()
            if self._paused:
                await self._park()
                return PHASE_CATCH_UP
            if self._tail_error is not None:
                error, self._tail_error = self._tail_error, None
                self._tail_task = None
                raise error

            now = self._clock.now()
            deadline = next_reconcile
            if self._first_buffered_at is not None:
                deadline = min(
                    deadline, self._after(self._first_buffered_at, live.flush_every_seconds)
                )
            timeout = min(max((deadline - now).total_seconds(), 0.0), _POLL_SECONDS)
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout)
            except TimeoutError:
                event = None
            self._take(event)
            while not self._queue.empty():
                self._take(self._queue.get_nowait())

            now = self._clock.now()
            if self._buffer and (
                len(self._buffer) >= live.flush_every_messages
                or (
                    self._first_buffered_at is not None
                    and now >= self._after(self._first_buffered_at, live.flush_every_seconds)
                )
            ):
                await self._flush()
            if self._recheck_requested and self._backfill_finished():
                await self._do_recheck()
            if now >= next_reconcile:
                await self._flush()
                return PHASE_CATCH_UP

    def _backfill_finished(self) -> bool:
        state = self._state or load_state(self.folder)
        return state is not None and state.backfill.done

    def _seconds_from_now(self, seconds: float) -> datetime:
        return self._clock.now() + timedelta(seconds=seconds)

    @staticmethod
    def _after(start: datetime, seconds: float) -> datetime:
        return start + timedelta(seconds=seconds)

    def _take(self, event: ChatEvent | None) -> None:
        if event is None:
            return
        if not self._buffer:
            self._first_buffered_at = self._clock.now()
        self._buffer.append(event)

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            events, self._buffer = self._buffer, []
            self._first_buffered_at = None
            try:
                state = self._state_for_flush()
            except BaseException:
                self._requeue(events)
                raise
            if state is None:
                log.warning("dropped %s buffered events of chat %s", len(events), self.chat_id)
                return
            records = self._records_from(events, state)
            try:
                self._state = self._writer().append(state, records) if records else state
            except BaseException:
                self._state_suspect = True
                self._requeue(events)
                raise
            log.debug("flushed %s records of chat %s", len(records), self.chat_id)

    def _state_for_flush(self) -> ChatState | None:
        """The data may have been written before a failed state save: realign from the files."""
        if self._state_suspect and self.folder.is_dir():
            state = recover_chat(
                self.folder,
                now=self._clock.now(),
                fallback_chat_id=self.chat_id,
                fallback_title=self._chat.title,
            )
            self._state_suspect = False
            return state
        return load_state(self.folder)

    def _requeue(self, events: list[ChatEvent]) -> None:
        self._buffer = events + self._buffer
        self._first_buffered_at = self._clock.now()

    def _drain_queue(self) -> None:
        while not self._queue.empty():
            self._take(self._queue.get_nowait())

    def _records_from(self, events: list[ChatEvent], state: ChatState) -> list[Record]:
        events_config = self._config.events
        records: list[Record] = []
        seen: set[int] = set()
        for event in events:
            if isinstance(event, NewMessageEvent):
                msg_id = event.record.msg_id
                if msg_id > state.last_id and msg_id > state.floor_id and msg_id not in seen:
                    seen.add(msg_id)
                    records.append(event.record)
            elif isinstance(event, EditedMessageEvent):
                message = event.record
                if events_config.track_edits and message.msg_id >= state.floor_id:
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
            elif events_config.track_deletes and event.chat_id == self.chat_id:
                ids = tuple(i for i in event.msg_ids if i >= state.floor_id)
                if ids:
                    records.append(
                        DeleteRecord(
                            chat_id=self.chat_id,
                            msg_ids=ids,
                            fetched_at=self._clock.now(),
                            detected_by=DETECTED_EVENT,
                        )
                    )
        return records

    async def _do_recheck(self) -> None:
        days = self._recheck_days or self._config.recheck.days
        self._recheck_requested = False
        self._recheck_days = None
        await self._flush()
        state = self._require_state()
        found = await self._flood(
            lambda: self._recheck(
                self._gateway,
                self.folder,
                state,
                now=self._clock.now(),
                days=days,
                track_edits=self._config.events.track_edits,
                track_deletes=self._config.events.track_deletes,
            )
        )
        async with self._lock:
            state = replace(self._require_state(), last_recheck_at=self._clock.now())
            records = [
                r
                for r in found
                if not (isinstance(r, MessageRecord) and r.msg_id <= state.floor_id)
            ]
            writer = self._writer()
            self._state = writer.append(state, records) if records else writer.update_state(state)
        log.info("recheck of chat %s: %s records", self.chat_id, len(records))

    def _ensure_tail(self) -> None:
        if self._tail_task is not None and not self._tail_task.done():
            return
        state = self._state or load_state(self.folder)
        if state is None or state.backfill.done:
            return
        self._tail_task = asyncio.create_task(self._tail_runner())

    async def _tail_runner(self) -> None:
        try:
            await self._flood(self._tail_backfill)
        except _Stop, _Refetch:
            return
        except Exception as error:
            self._tail_error = error
            self._wake()

    async def _tail_backfill(self) -> None:
        state = load_state(self.folder)
        if state is None:
            raise _StateGone
        offset = state.backfill.oldest_done_id or state.floor_id
        if state.backfill.done:
            return
        if state.floor_id and state.floor_id >= offset:
            await self._finish_tail()
            return

        batch_size = self._config.backfill.batch_size
        month: str | None = None
        pending: list[MessageRecord] = []
        seen = 0
        async for record in self._gateway.iter_history(
            self.chat_id, offset_id=offset, min_id=state.floor_id
        ):
            await self._tail_gate()
            key = month_key(record.date)
            if month is not None and key < month:
                await self._write_tail_month(month, pending)
                pending = []
            if month is None or key < month:
                month = key
            pending.append(record)
            seen += 1
            if seen % batch_size == 0:
                await self._clock.sleep(self._config.backfill.pause_between_requests_sec)
        if month is not None:
            await self._write_tail_month(month, pending)
        await self._finish_tail()

    async def _tail_gate(self) -> None:
        while True:
            if self._stopping:
                raise _Stop
            if self._refetch:
                raise _Refetch
            if self._backfill_gate.is_set():
                return
            await self._backfill_gate.wait()

    async def _write_tail_month(self, month: str, records: list[MessageRecord]) -> None:
        async with self._lock:
            state = self._require_state()
            kept = [r for r in records if r.msg_id > state.floor_id]
            previous = state.backfill.oldest_done_id
            oldest = min((r.msg_id for r in records), default=previous)
            state = replace(
                state,
                backfill=replace(state.backfill, oldest_done_id=min(oldest, previous or oldest)),
            )
            writer = self._writer()
            self._state = (
                writer.merge_month(state, month, kept) if kept else writer.update_state(state)
            )
        self._refresh_oldest(self._state)
        log.info("tail month %s of chat %s: %s messages", month, self.chat_id, len(kept))

    async def _finish_tail(self) -> None:
        async with self._lock:
            state = self._require_state()
            state = replace(state, backfill=replace(state.backfill, done=True))
            self._state = self._writer().update_state(state)
        log.info("backfill of chat %s is complete", self.chat_id)
        self._wake()

    async def _cancel_tail(self) -> None:
        task, self._tail_task = self._tail_task, None
        self._tail_error = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def _checkpoint(self) -> None:
        self._raise_if_interrupted()
        if self._paused:
            await self._park()
            self._raise_if_interrupted()

    async def _pause_between_requests(self) -> None:
        await self._clock.sleep(self._config.backfill.pause_between_requests_sec)
        await self._checkpoint()

    def _raise_if_interrupted(self) -> None:
        if self._stopping:
            raise _Stop
        if self._refetch:
            raise _Refetch

    async def _park(self) -> None:
        await self._flush()
        previous = self._phase
        await self._persist_phase(PHASE_PAUSED)
        await self._resumed.wait()
        await self._persist_phase(previous)

    async def _set_phase(self, phase: str) -> None:
        self._phase = phase
        await self._persist_phase(phase)

    async def _persist_phase(self, phase: str) -> None:
        async with self._lock:
            state = load_state(self.folder)
            if state is None:
                raise _StateGone
            if state.phase != phase:
                state = self._writer().update_state(replace(state, phase=phase))
            self._state = state

    async def _mark_no_access(self) -> None:
        self._phase = PHASE_NO_ACCESS
        async with self._lock:
            state = load_state(self.folder)
            if state is not None:
                self._state = self._writer().update_state(replace(state, phase=PHASE_NO_ACCESS))
        self._error = "no access"
        self._notifier.notify(Level.ERROR, self._chat.title, "No access to the chat; data kept")
        log.error("no access to chat %s", self.chat_id)

    async def _discard_events_until_stop_or_refetch(self) -> None:
        while not self._stopping and not self._refetch:
            await self._queue.get()

    async def _flood[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        while True:
            try:
                return await operation()
            except FloodWait as wait:
                log.warning("FloodWait %s s in chat %s", wait.seconds, self.chat_id)
                if wait.seconds > _LONG_FLOOD_SECONDS:
                    self._notifier.notify(
                        Level.WARNING,
                        self._chat.title,
                        f"Telegram asked to wait {wait.seconds} s; this chat sleeps",
                    )
                await self._clock.sleep(wait.seconds)

    def _require_state(self) -> ChatState:
        state = load_state(self.folder)
        if state is None:
            raise _StateGone
        self._state = state
        return state

    def _writer(self) -> ChunkWriter:
        return ChunkWriter(
            self.folder, self._config.output.max_chunk_mb * _BYTES_PER_MB, self._clock.now
        )

    def _refresh_oldest(self, state: ChatState | None) -> None:
        if state is None:
            return
        folder = self.folder
        for key in sorted(state.chunks):
            try:
                for record in iter_part_records(folder / f"{key}.jsonl"):
                    if isinstance(record, MessageRecord):
                        self._oldest_date = record.date
                        return
            except OSError:
                continue

    def _update_gate(self) -> None:
        open_ = not (self._paused or self._backfill_paused) or self._stopping or self._refetch
        if open_:
            self._backfill_gate.set()
        else:
            self._backfill_gate.clear()

    def _wake(self) -> None:
        self._queue.put_nowait(None)
