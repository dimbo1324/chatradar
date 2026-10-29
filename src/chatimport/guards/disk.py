"""Automatic disk guard (spec §8.5)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from chatimport.runtime import Level

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import DiskConfig
    from chatimport.ports import Clock, DiskUsage
    from chatimport.runtime import ChatRegistry, Notifier
    from chatimport.trim import Trimmer

log = logging.getLogger(__name__)

GIB: Final = 1024**3
TITLE: Final = "Disk space"


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
        if start_free >= self._config.low_watermark_gb * GIB:
            return False
        for controller in self._registry.all():
            controller.pause_backfill()

        high = self._config.high_watermark_gb * GIB
        deleted = 0
        free = start_free
        exhausted = False
        while free < high:
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
