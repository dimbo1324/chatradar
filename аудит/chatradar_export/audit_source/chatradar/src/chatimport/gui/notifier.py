"""`QtNotifier`: the service's `Notifier` whose notes arrive on the Qt thread as a signal.

`notify` may be called from any thread; the note crosses to the main thread through a queued
signal and is re-emitted as `delivered`. Notes never carry message text or sender names.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from chatimport.runtime import Level

log = logging.getLogger("chatimport.notify")


class QtNotifier(QObject):
    delivered = Signal(object, str, str)

    _incoming = Signal(object, str, str)

    def __init__(self) -> None:
        super().__init__()
        self._incoming.connect(self._on_incoming)

    def notify(self, level: Level, title: str, message: str) -> None:
        log.log(level.logging_level, "%s: %s", title, message)
        self._incoming.emit(level, title, message)

    @Slot(object, str, str)
    def _on_incoming(self, level: object, title: str, message: str) -> None:
        if isinstance(level, Level):
            self.delivered.emit(level, title, message)
