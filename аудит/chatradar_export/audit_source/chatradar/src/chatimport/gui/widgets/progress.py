"""Progress: a determinate or indeterminate bar, and a thin busy stripe for page tops.

Both are painted from the palette. An indeterminate bar only runs its animation while visible,
so a hidden page costs nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import DURATION, SPACE
from chatimport.gui.widgets.base import Tone, bind_kit

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent, QPaintEvent, QShowEvent

    from chatimport.gui.kit import UiKit

_SWEEP_MS: Final = 1400
_BLOCK: Final = 0.38


class ProgressBar(QWidget):
    """`set_value(0..1)` for a fraction, `set_value(None)` for "working, no estimate"."""

    def __init__(
        self,
        kit: UiKit,
        *,
        tone: Tone = "accent",
        height: int = SPACE[3],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self._tone: Tone = tone
        self._height = height
        self._value: float | None = None
        self._shown: float = 0.0
        self._phase = 0.0
        self._fill = QVariantAnimation(self)
        self._fill.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fill.valueChanged.connect(self._on_fill)
        self._sweep = QVariantAnimation(self)
        self._sweep.setStartValue(0.0)
        self._sweep.setEndValue(1.0)
        self._sweep.setDuration(_SWEEP_MS)
        self._sweep.setLoopCount(-1)
        self._sweep.valueChanged.connect(self._on_sweep)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind_kit(kit, theme=self.update, zoom=self._resize)
        self._resize()

    @property
    def value(self) -> float | None:
        return self._value

    def set_tone(self, tone: Tone) -> None:
        self._tone = tone
        self.update()

    def set_value(self, value: float | None) -> None:
        self._value = None if value is None else min(max(value, 0.0), 1.0)
        if self._value is None:
            self._fill.stop()
            self._sync_sweep()
        else:
            self._sweep.stop()
            self._fill.stop()
            self._fill.setStartValue(self._shown)
            self._fill.setEndValue(self._value)
            self._fill.setDuration(DURATION["slow"])
            self._fill.start()
        self.update()

    def _resize(self) -> None:
        self.setFixedHeight(self.kit.px(self._height))

    def _on_fill(self, value: object) -> None:
        self._shown = float(value) if isinstance(value, float | int) else self._shown
        self.update()

    def _on_sweep(self, value: object) -> None:
        self._phase = float(value) if isinstance(value, float | int) else 0.0
        self.update()

    def _sync_sweep(self) -> None:
        running = self._sweep.state() == QVariantAnimation.State.Running
        if self._value is None and self.isVisible():
            if not running:
                self._sweep.start()
        elif running:
            self._sweep.stop()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_sweep()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._sweep.stop()

    def _track_color(self) -> QColor:
        return QColor(self.kit.palette.surface_active)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(rect, self._track_color())
        fill = QColor(tone_colors(self.kit.palette, self._tone)[2])
        if self._tone == "accent":
            fill = QColor(self.kit.palette.accent)
        if self._value is None:
            width = rect.width() * _BLOCK
            left = -width + (rect.width() + width) * self._phase
            painter.fillRect(QRectF(left, 0, width, rect.height()), fill)
        else:
            painter.fillRect(QRectF(0, 0, rect.width() * self._shown, rect.height()), fill)
        event.accept()


class BusyStripe(ProgressBar):
    """A 2 px indeterminate line on a transparent track, shown while something is loading."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(kit, tone="accent", height=SPACE[1], parent=parent)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.setVisible(active)
        self.set_value(None)

    def _track_color(self) -> QColor:
        return QColor(Qt.GlobalColor.transparent)
