"""The service task that keeps the combined file current.

A timer wakes every `TICK_SECONDS`; when `[merged]` is enabled and `every_minutes` have passed
since the last attempt it runs one build in a worker thread, which itself does nothing unless
some chat changed. There is no trigger after live flushes: a timer is enough for a derived copy.
The config is read through a callable, so a reloaded `config.toml` takes effect without a restart.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Final

from chatimport.commands import finish
from chatimport.merged_export import build_merged, last_result
from chatimport.records import format_dt

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.config import MergedConfig
    from chatimport.merged_export import MergedResult
    from chatimport.ports import Clock

log = logging.getLogger(__name__)

TICK_SECONDS: Final = 30


class MergedExporter:
    def __init__(self, root: Path, config: Callable[[], MergedConfig], clock: Clock) -> None:
        self._root = root
        self._config = config
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last: MergedResult | None = None
        self._loaded = False
        self._attempted: datetime | None = None
        self._building = False
        self._failed = False

    @property
    def building(self) -> bool:
        return self._building

    def last(self) -> MergedResult | None:
        if not self._loaded:
            self._loaded = True
            self._last = last_result(self._root)
        return self._last

    def snapshot(self) -> dict[str, Any]:
        last = self.last()
        return {
            "enabled": self._config().enabled,
            "last_built_at": format_dt(last.built_at) if last is not None else None,
            "path": str(last.path) if last is not None else None,
            "records": last.records if last is not None else 0,
            "bytes": last.bytes if last is not None else 0,
            "building": self._building,
            "failed": self._failed,
        }

    async def build(
        self, fmt: str | None = None, include_names: bool | None = None, *, force: bool = False
    ) -> MergedResult:
        config = self._config()
        async with self._lock:
            self._building = True
            try:
                result = await finish(
                    asyncio.ensure_future(
                        asyncio.to_thread(
                            build_merged,
                            self._root,
                            now=self._clock.now(),
                            fmt=config.format if fmt is None else fmt,
                            include_names=(
                                config.include_names if include_names is None else include_names
                            ),
                            force=force,
                        )
                    )
                )
            except BaseException:
                self._failed = True
                raise
            finally:
                self._building = False
            self._failed = False
            self._loaded = True
            if not result.skipped or self._last is None:
                self._last = result
            return result

    async def tick(self) -> None:
        config = self._config()
        if not config.enabled:
            return
        now = self._clock.now()
        if (
            self._attempted is not None
            and (now - self._attempted).total_seconds() < config.every_minutes * 60
        ):
            return
        self._attempted = now
        await self.build()

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("combined file build failed")
            await self._clock.sleep(TICK_SECONDS)
