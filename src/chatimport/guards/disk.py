"""Automatic disk guard (spec §8.5) and the media download gate.

When free space falls below the low watermark, every unfinished history download is stopped
for good (spec §8.2.5): the floor moves up to where it got, `floor_reason = "disk"`, and the
backfill counts as done, so a restart does not refill the disk. `backfill --deeper` resumes it.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Final, Protocol

from chatimport.config import GIB
from chatimport.runtime import Level
from chatimport.storage.state import StateUnreadable, load_state, save_state

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import DiskConfig
    from chatimport.ports import Clock, DiskUsage
    from chatimport.runtime import ChatController, ChatRegistry, Notifier
    from chatimport.storage.state import ChatState
    from chatimport.trim import Trimmer

__all__ = ["FLOOR_REASON_DISK", "GIB", "TITLE", "DiskGuard", "MediaDiskGate"]

log = logging.getLogger(__name__)

TITLE: Final = "Disk space"
FLOOR_REASON_DISK: Final = "disk"


def _stopped(state: ChatState) -> ChatState:
    floor = state.backfill.oldest_done_id or min(
        (info.first_id for info in state.chunks.values() if info.first_id), default=0
    )
    return replace(
        state,
        floor_id=max(state.floor_id, floor),
        floor_reason=FLOOR_REASON_DISK,
        backfill=replace(state.backfill, done=True),
    )


class DiskGuard:
    def __init__(
        self,
        root: Path,
        registry: ChatRegistry,
        trimmer: Trimmer,
        config: DiskConfig,
        *,
        clock: Clock,
        disk: DiskUsage,
        notifier: Notifier,
    ) -> None:
        self._root = root
        self._registry = registry
        self._trimmer = trimmer
        self._config = config
        self._clock = clock
        self._disk = disk
        self._notifier = notifier

    async def run(self) -> None:
        while True:
            try:
                await self.check_once()
            except Exception:
                log.exception("disk guard check failed")
            await self._clock.sleep(self._config.check_every_minutes * 60)

    async def check_once(self) -> bool:
        """True when free space was below the low watermark and trimming was attempted."""
        start_free = self._disk.free_bytes(self._root)
        if start_free >= self._config.low_bytes:
            return False
        stopped = 0
        for controller in self._registry.all():
            controller.pause_backfill()
            if await self._stop_backfill(controller):
                stopped += 1
        if stopped:
            self._notifier.notify(
                Level.WARNING,
                TITLE,
                f"history download stopped in {stopped} chat(s) for lack of space; "
                "`chatimport backfill --deeper` continues it",
            )

        deleted = 0
        free = start_free
        exhausted = False
        while free < self._config.high_bytes:
            part = await self._trimmer.delete_oldest_part(self._config.protect_recent_days)
            if part is None:
                exhausted = True
                break
            deleted += 1
            free = self._disk.free_bytes(self._root)

        if exhausted:
            self._notifier.notify(
                Level.WARNING, TITLE, "space is low, everything allowed is already deleted"
            )
        if deleted:
            freed_gb = max(0, free - start_free) / GIB
            self._notifier.notify(
                Level.INFO, TITLE, f"freed {freed_gb:.1f} GB: deleted {deleted} parts"
            )
        log.info("disk guard ran", extra={"parts": deleted, "exhausted": exhausted})
        return True

    async def _stop_backfill(self, controller: ChatController) -> bool:
        """Persist the stop of an unfinished history download; True when one was stopped."""
        async with controller.lock:
            folder = controller.folder
            try:
                state = load_state(folder) if folder.is_dir() else None
            except StateUnreadable:
                log.warning("cannot stop the backfill now", extra={"chat_id": controller.chat_id})
                return False
            if state is None or state.backfill.done:
                return False
            stopped = replace(_stopped(state), updated_at=self._clock.now())
            save_state(folder, stopped)
        log.warning(
            "backfill stopped for lack of space",
            extra={"chat_id": controller.chat_id, "floor_id": stopped.floor_id},
        )
        return True


class Pausable(Protocol):
    def pause(self) -> None: ...

    def resume(self) -> None: ...


class MediaDiskGate:
    """Pauses media downloads below the low watermark and resumes them at the high one."""

    def __init__(
        self,
        root: Path,
        downloader: Pausable,
        config: DiskConfig,
        *,
        disk: DiskUsage,
        clock: Clock,
    ) -> None:
        self._root = root
        self._downloader = downloader
        self._config = config
        self._disk = disk
        self._clock = clock

    def check_once(self) -> None:
        free = self._disk.free_bytes(self._root)
        if free < self._config.low_bytes:
            self._downloader.pause()
        elif free >= self._config.high_bytes:
            self._downloader.resume()

    async def run(self) -> None:
        while True:
            self.check_once()
            await self._clock.sleep(self._config.check_every_minutes * 60)
