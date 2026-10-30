"""Everything that runs against one data root: the chat workers and the helper tasks around
them. A root change stops this runtime and starts a new one on the new root."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from chatimport.guards.disk import DiskGuard, MediaDiskGate
from chatimport.guards.folders import FolderWatcher
from chatimport.media import MediaDownloader
from chatimport.recheck import RecheckScheduler, compute_recheck
from chatimport.resolution import tracked_chat
from chatimport.router import Router
from chatimport.runtime import BackfillSlots, ChatRegistry
from chatimport.status import StatusWriter
from chatimport.storage.state import StateUnreadable, load_state
from chatimport.supervisor import Supervisor
from chatimport.trim import Trimmer
from chatimport.worker import ChatWorker

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from datetime import datetime
    from pathlib import Path

    from chatimport.config import Config
    from chatimport.ports import Clock, DiskUsage, TelegramGateway
    from chatimport.resolution import ErrorBook, ResolvedEntry
    from chatimport.runtime import ChatController, Notifier, TrackedChat

log = logging.getLogger(__name__)


def make_worker(
    chat: TrackedChat,
    *,
    root: Path,
    gateway: TelegramGateway,
    config: Config,
    clock: Clock,
    notifier: Notifier,
    slots: BackfillSlots,
) -> ChatWorker:
    return ChatWorker(
        chat,
        root=root,
        gateway=gateway,
        config=config,
        clock=clock,
        notifier=notifier,
        recheck=compute_recheck,
        slots=slots,
    )


def _last_recheck_at(controller: ChatController) -> datetime | None:
    try:
        state = load_state(controller.folder)
    except StateUnreadable:
        log.warning("state unreadable; recheck age unknown", extra={"chat_id": controller.chat_id})
        return None
    return state.last_recheck_at if state is not None else None


def _backfill_done(worker: ChatWorker) -> bool:
    try:
        state = load_state(worker.folder)
    except StateUnreadable:
        log.warning("state unreadable; launch staggered", extra={"chat_id": worker.chat_id})
        return False
    return state is not None and state.backfill.done


class ServiceRuntime:
    def __init__(
        self,
        root: Path,
        *,
        config: Config,
        gateway: TelegramGateway,
        clock: Clock,
        notifier: Notifier,
        disk: DiskUsage,
        errors: ErrorBook,
        service_state: Callable[[], str],
    ) -> None:
        self.root = root
        self.config = config
        self.gateway = gateway
        self._clock = clock
        self._notifier = notifier
        self._disk = disk
        self._errors = errors
        self.registry = ChatRegistry()
        self.supervisor = Supervisor(clock, notifier)
        self.slots = BackfillSlots(config.backfill.max_parallel_chats)
        self.router = Router(self.registry, root, clock=clock)
        self.trimmer = Trimmer(
            root, self.registry, clock=clock, max_chunk_bytes=config.output.max_chunk_bytes
        )
        self.status = StatusWriter(
            root,
            self.registry,
            self.supervisor,
            clock=clock,
            disk=disk,
            low_watermark_gb=config.disk.low_watermark_gb,
            service_state=service_state,
        )
        self.scheduler = RecheckScheduler(self.registry, config.recheck, clock, _last_recheck_at)
        self._aux_tasks: list[asyncio.Task[None]] = []
        self._launches = 0

    def start(self, entries: Iterable[ResolvedEntry], on_fatal: Callable[[], None]) -> None:
        self._errors.attach(self.status)
        self.add(entries)
        config = self.config
        guard = DiskGuard(
            self.root,
            self.registry,
            self.trimmer,
            config.disk,
            clock=self._clock,
            disk=self._disk,
            notifier=self._notifier,
        )
        watcher = FolderWatcher(
            self.root, self.registry, config.watch, clock=self._clock, notifier=self._notifier
        )
        self._spawn_aux("folder-watcher", watcher.run)
        self._spawn_aux("disk-guard", guard.run)
        self._spawn_aux("recheck", self.scheduler.run)
        self._spawn_aux("status", self.status.run)
        if config.media.enabled:
            downloader = MediaDownloader(
                self.registry,
                self.gateway,
                config.media,
                clock=self._clock,
                max_chunk_bytes=config.output.max_chunk_bytes,
            )
            gate = MediaDiskGate(
                self.root, downloader, config.disk, disk=self._disk, clock=self._clock
            )
            self._spawn_aux("media", downloader.run)
            self._spawn_aux("media-guard", gate.run)
        self._aux_tasks.append(asyncio.create_task(self._watch_fatal(on_fatal)))

    def add(self, entries: Iterable[ResolvedEntry]) -> None:
        """Register a worker for every chat not yet running and launch them."""
        workers = [worker for item in entries if (worker := self._register(item)) is not None]
        self._launch(workers)

    async def remove(self, chat_id: int) -> None:
        controller = self.registry.remove(chat_id)
        if controller is not None:
            await controller.stop()

    async def stop(self) -> None:
        self._errors.attach(None)
        for task in self._aux_tasks:
            task.cancel()
        await asyncio.gather(*self._aux_tasks, return_exceptions=True)
        results = await asyncio.gather(
            *(controller.stop() for controller in self.registry.all()), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                log.error("a worker did not stop cleanly: %s", type(result).__name__)
        await self.supervisor.stop_all()

    async def _watch_fatal(self, on_fatal: Callable[[], None]) -> None:
        await self.supervisor.wait_fatal()
        log.error("fatal task failure, shutting down")
        on_fatal()

    def _spawn_aux(self, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        self._aux_tasks.append(self.supervisor.spawn(name, factory))

    def _register(self, item: ResolvedEntry) -> ChatWorker | None:
        chat_id = item.resolved.chat_id
        if chat_id is None or self.registry.get(chat_id) is not None:
            return None
        worker = make_worker(
            tracked_chat(*item),
            root=self.root,
            gateway=self.gateway,
            config=self.config,
            clock=self._clock,
            notifier=self._notifier,
            slots=self.slots,
        )
        self.registry.add(worker)
        return worker

    def _launch(self, workers: list[ChatWorker]) -> None:
        fresh: list[ChatWorker] = []
        for worker in workers:
            if _backfill_done(worker):
                self._spawn_worker(worker)
            else:
                fresh.append(worker)
        if fresh:
            self._launches += 1
            self.supervisor.spawn(
                f"launch-{self._launches}", lambda: self._stagger(fresh), restart=False
            )

    async def _stagger(self, workers: list[ChatWorker]) -> None:
        pause = self.config.backfill.pause_between_chats_sec
        for index, worker in enumerate(workers):
            if index:
                await self._clock.sleep(pause)
            if self.registry.get(worker.chat_id) is worker:
                self._spawn_worker(worker)

    def _spawn_worker(self, worker: ChatWorker) -> None:
        self.supervisor.spawn(f"worker-{worker.chat_id}", worker.run)
