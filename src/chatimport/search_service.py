"""The service task that keeps the search index current.

The index is a derived cache of the stored parts, written only here. A timer wakes every
`[search] interval_seconds`; each wake runs bounded `IndexBuilder.step()` calls in a worker
thread (the event loop never waits on SQLite) and continues straight away while there is work,
so a long initial build leaves short pauses between batches. Repeated failures delete the file
and rebuild it. The config is read through a callable, so a reloaded `config.toml` takes effect
without a restart.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from chatimport.commands import in_thread
from chatimport.records import format_dt
from chatimport.search_db import fts5_trigram_available
from chatimport.search_index import SearchIndex, open_writer, reset_index
from chatimport.search_indexer import IndexBuilder, StepResult
from chatimport.search_types import IndexState

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.config import SearchConfig
    from chatimport.ports import Clock

log = logging.getLogger(__name__)

BUSY_PAUSE_SECONDS: Final = 0.05
FAILURES_BEFORE_REBUILD: Final = 3


class SearchIndexer:
    def __init__(self, root: Path, config: Callable[[], SearchConfig], clock: Clock) -> None:
        self._root = root
        self._config = config
        self._clock = clock
        self._index: SearchIndex | None = None
        self._builder: IndexBuilder | None = None
        self._state = IndexState.BUILDING
        self._indexed = 0
        self._total = 0
        self._updated: datetime | None = None
        self._failures = 0
        self._unavailable = False

    def snapshot(self) -> dict[str, Any]:
        enabled = self._config().enabled
        active = enabled and not self._unavailable
        return {
            "enabled": enabled,
            "state": (self._state if active else IndexState.DISABLED).value,
            "indexed": self._indexed,
            "total": self._total,
            "updated_at": format_dt(self._updated) if self._updated is not None else None,
        }

    def _work(self) -> StepResult:
        if self._builder is None:
            if not self._root.is_dir():
                return StepResult(False, self._state, 0, 0, None)
            self._index = open_writer(self._root)
            self._builder = IndexBuilder(self._index, self._root, self._clock.now)
        return self._builder.step()

    def close(self) -> None:
        index, self._index, self._builder = self._index, None, None
        if index is not None:
            index.close()

    def _rebuild(self) -> None:
        self.close()
        reset_index(self._root)
        self._state = IndexState.BUILDING
        self._indexed = self._total = 0
        self._updated = None

    async def tick(self) -> bool:
        """One step of work; True when another step is waiting."""
        if not self._config().enabled:
            self.close()
            return False
        if not fts5_trigram_available():
            if not self._unavailable:
                log.warning("search is off: this SQLite has no FTS5 trigram tokenizer")
            self._unavailable = True
            return False
        self._unavailable = False
        try:
            result = await in_thread(self._work)
        except Exception:
            self._failures += 1
            if self._failures >= FAILURES_BEFORE_REBUILD:
                self._failures = 0
                await in_thread(self._rebuild)
            raise
        self._failures = 0
        self._state = result.state
        self._indexed = result.indexed
        self._total = result.total
        self._updated = result.updated_at
        return result.more

    async def run(self) -> None:
        try:
            while True:
                more = False
                try:
                    more = await self.tick()
                except Exception:
                    log.exception("search index update failed")
                pause = BUSY_PAUSE_SECONDS if more else max(1, self._config().interval_seconds)
                await self._clock.sleep(pause)
        finally:
            self.close()
