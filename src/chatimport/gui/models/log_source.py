"""Feeds the log page: a worker-thread first load, then a once-a-second follow on the main thread.

The initial load and "load older" read big chunks, so they run on a worker thread and are
delivered to the main thread by `MainThreadRunner`. Following reads at most a megabyte of new
bytes per tick, which is quick enough to do in place. Signals are emitted on the main thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, QTimer, Signal

from chatimport.gui.models.log_tail import LogTail
from chatimport.gui.models.ticker import shared_ticker
from chatimport.gui.pages.support import MainThreadRunner

if TYPE_CHECKING:
    from concurrent.futures import Future
    from pathlib import Path

    from chatimport.gui.models.log_parser import LogRecord
    from chatimport.gui.models.log_tail import OlderBatch

INITIAL_RECORDS: Final = 2000
OLDER_RECORDS: Final = 1000


class LogSource(QObject):
    loaded = Signal(list, bool)
    appended = Signal(list)
    older = Signal(list, bool)
    exists_changed = Signal(bool)
    rotated = Signal()
    busy_changed = Signal(bool)
    failed = Signal()

    def __init__(self, directory: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.tail = LogTail(directory)
        self._runner = MainThreadRunner(self)
        self._ticker = shared_ticker()
        self._ready = False
        self._busy = False
        self._following = False
        self._exists: bool | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def exists(self) -> bool:
        return bool(self._exists)

    @property
    def has_older(self) -> bool:
        return self.tail.has_older

    def start(self) -> None:
        """First load; safe to call again to reload from scratch."""
        self._ready = False
        self._set_busy(True)
        self._runner.submit(lambda: self.tail.load_tail(INITIAL_RECORDS), self._on_loaded)

    def load_older(self) -> None:
        if self._busy or not self.tail.has_older:
            return
        self._set_busy(True)
        self._runner.submit(lambda: self.tail.load_older(OLDER_RECORDS), self._on_older)

    def forget_older(self) -> None:
        self.tail.forget_older()

    def set_following(self, following: bool) -> None:
        """Poll once a second only while the page is on screen; catch up at once on return."""
        if following == self._following:
            return
        self._following = following
        if following:
            self._ticker.second.connect(self._poll)
            self._poll()
        else:
            self._ticker.second.disconnect(self._poll)

    def _set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.busy_changed.emit(busy)

    def _on_loaded(self, future: Future[list[LogRecord]]) -> None:
        self._set_busy(False)
        if future.cancelled() or future.exception() is not None:
            self.failed.emit()
            return
        self._ready = True
        self._exists = self.tail.path.exists()
        self.exists_changed.emit(self._exists)
        self.loaded.emit(future.result(), self.tail.has_older)

    def _on_older(self, future: Future[OlderBatch]) -> None:
        self._set_busy(False)
        if future.cancelled() or future.exception() is not None:
            self.failed.emit()
            return
        batch = future.result()
        self.older.emit(batch.records, batch.exhausted)

    def _poll(self) -> None:
        if not self._ready or self._busy:
            return
        result = self.tail.poll()
        if result.exists != self._exists:
            self._exists = result.exists
            self.exists_changed.emit(result.exists)
        if result.rotated:
            self.rotated.emit()
        if result.records:
            self.appended.emit(result.records)
        if result.more:
            QTimer.singleShot(0, self._poll)
