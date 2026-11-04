"""One shared clock for the whole window: a 1 s tick for relative times, a fast animation tick.

Relative times ("3 min 5 s ago") and retry countdowns are recomputed from `now()` on every
`second` tick instead of being stored, so they can never drift from the snapshot. The `frame`
tick runs only while something holds an animation (`acquire_animation`), so an idle window
wakes once a second.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

if TYPE_CHECKING:
    from collections.abc import Callable

SECOND_MS: Final = 1000
FRAME_MS: Final = 33
SWEEP_SECONDS: Final = 1.6


def utc_now() -> datetime:
    return datetime.now(UTC)


class SecondTicker(QObject):
    second = Signal()
    frame = Signal(float)

    def __init__(
        self, clock: Callable[[], datetime] = utc_now, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.clock = clock
        self._animations = 0
        self._second = QTimer(self)
        self._second.setInterval(SECOND_MS)
        self._second.timeout.connect(self.second)
        self._second.start()
        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self._on_frame)

    def now(self) -> datetime:
        return self.clock()

    @property
    def animating(self) -> bool:
        return self._animations > 0

    def acquire_animation(self) -> None:
        self._animations += 1
        if self._animations == 1:
            self._frame.start()

    def release_animation(self) -> None:
        self._animations = max(self._animations - 1, 0)
        if self._animations == 0:
            self._frame.stop()

    def _on_frame(self) -> None:
        self.frame.emit((time.monotonic() % SWEEP_SECONDS) / SWEEP_SECONDS)


def shared_ticker() -> SecondTicker:
    """The application's single ticker, created on first use as a child of the application."""
    app = QCoreApplication.instance()
    existing = app.findChild(SecondTicker) if app is not None else None
    if existing is not None:
        return existing
    return SecondTicker(parent=app)
