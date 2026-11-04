"""UI zoom: one factor every size in the window is multiplied by.

The factor starts "auto" (derived from the primary screen) and becomes the owner's choice as
soon as they step it; `reset` returns to auto, not to 100 %. Stepping works in integer
hundredths because `1.2 / 0.05` is not exactly 24 in floats and a step would silently do nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, QWheelEvent

from chatimport.gui.tokens import ZOOM_MAX, ZOOM_MIN, ZOOM_STEP

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

_REFERENCE_WIDTH: Final = 1920
_AUTO_MIN: Final = 0.85
_AUTO_MAX: Final = 1.5


def round_factor(factor: float) -> float:
    return round(factor * 100) / 100


def clamp_factor(factor: float) -> float:
    if factor != factor or factor in (float("inf"), float("-inf")):
        return 1.0
    return round_factor(min(max(factor, ZOOM_MIN), ZOOM_MAX))


def step_from(factor: float, direction: int) -> float:
    """The next multiple of the step in `direction` (+1 or -1), so 0.87 steps to 0.9 or 0.85."""
    hundredths = round(factor * 100)
    step = round(ZOOM_STEP * 100)
    grid = hundredths // step + 1 if direction > 0 else -(-hundredths // step) - 1
    return clamp_factor(grid * step / 100)


def auto_factor_for_width(logical_width: int) -> float:
    """Screen-derived default: a 1366 px laptop reads at 85 %, 1920 px at 100 %, 4K at 150 %."""
    if logical_width <= 0:
        return 1.0
    raw = min(max(logical_width / _REFERENCE_WIDTH, _AUTO_MIN), _AUTO_MAX)
    return clamp_factor(round(raw / ZOOM_STEP) * ZOOM_STEP)


def screen_auto_factor() -> float:
    screen = QGuiApplication.primaryScreen()
    return auto_factor_for_width(screen.availableGeometry().width()) if screen else 1.0


class ZoomManager(QObject):
    changed = Signal(float)

    def __init__(self, stored: float | None = None, auto_factor: float | None = None) -> None:
        super().__init__()
        self._auto_factor = clamp_factor(auto_factor if auto_factor is not None else 1.0)
        self._auto = stored is None
        self._factor = self._auto_factor if stored is None else clamp_factor(stored)

    @property
    def factor(self) -> float:
        return self._factor

    @property
    def auto(self) -> bool:
        return self._auto

    @property
    def percent(self) -> int:
        return round(self._factor * 100)

    @property
    def stored(self) -> float | None:
        return None if self._auto else self._factor

    @property
    def can_zoom_in(self) -> bool:
        return self._factor < ZOOM_MAX

    @property
    def can_zoom_out(self) -> bool:
        return self._factor > ZOOM_MIN

    def scaled(self, pixels: float) -> int:
        return round(pixels * self._factor)

    def set_factor(self, factor: float) -> None:
        self._apply(clamp_factor(factor), auto=False)

    def zoom_in(self) -> None:
        self._apply(step_from(self._factor, 1), auto=False)

    def zoom_out(self) -> None:
        self._apply(step_from(self._factor, -1), auto=False)

    def reset(self) -> None:
        self._apply(self._auto_factor, auto=True)

    def _apply(self, factor: float, *, auto: bool) -> None:
        moved = factor != self._factor or auto != self._auto
        self._auto = auto
        self._factor = factor
        if moved:
            self.changed.emit(factor)


class _CtrlWheelFilter(QObject):
    def __init__(self, zoom: ZoomManager, parent: QObject) -> None:
        super().__init__(parent)
        self._zoom = zoom

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not (
            event.type() == QEvent.Type.Wheel
            and isinstance(event, QWheelEvent)
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            return False
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom.zoom_in()
        elif delta < 0:
            self._zoom.zoom_out()
        return True


def install_zoom_inputs(zoom: ZoomManager, window: QWidget) -> None:
    """Ctrl+= / Ctrl++ / Ctrl+- / Ctrl+0 and Ctrl+wheel anywhere in `window`."""
    bindings = (
        ("Ctrl+=", zoom.zoom_in),
        ("Ctrl++", zoom.zoom_in),
        ("Ctrl+-", zoom.zoom_out),
        ("Ctrl+0", zoom.reset),
    )
    for sequence, action in bindings:
        shortcut = QShortcut(QKeySequence(sequence), window)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(action)
    app = QGuiApplication.instance()
    if app is not None:
        app.installEventFilter(_CtrlWheelFilter(zoom, window))
