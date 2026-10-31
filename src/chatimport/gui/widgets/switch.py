"""A toggle switch, and a settings row that pairs it with a label and an explanation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.tokens import DURATION, SPACE
from chatimport.gui.widgets.base import KEYBOARD_REASONS, bind_kit, set_role

if TYPE_CHECKING:
    from PySide6.QtGui import QFocusEvent, QMouseEvent, QPaintEvent

    from chatimport.gui.kit import UiKit

_TRACK_W: Final = 36
_TRACK_H: Final = 20
_KNOB_GAP: Final = 3


class Switch(QAbstractButton):
    def __init__(self, kit: UiKit, *, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._keyboard_focus = False
        self.kit = kit
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._position = 1.0 if checked else 0.0
        self._slide = QVariantAnimation(self)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide.setDuration(DURATION["base"])
        self._slide.valueChanged.connect(self._on_slide)
        self.toggled.connect(self._animate)
        bind_kit(kit, theme=self.update, zoom=self.updateGeometry)

    def sizeHint(self) -> QSize:
        return QSize(self.kit.px(_TRACK_W + 4), self.kit.px(_TRACK_H + 4))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _animate(self, checked: bool) -> None:
        self._slide.stop()
        self._slide.setStartValue(self._position)
        self._slide.setEndValue(1.0 if checked else 0.0)
        self._slide.start()

    def _on_slide(self, value: object) -> None:
        if isinstance(value, float | int):
            self._position = float(value)
        self.update()

    def focusInEvent(self, event: QFocusEvent) -> None:
        self._keyboard_focus = event.reason() in KEYBOARD_REASONS
        super().focusInEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self.kit.palette
        px = self.kit.px
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(
            (self.width() - px(_TRACK_W)) / 2,
            (self.height() - px(_TRACK_H)) / 2,
            px(_TRACK_W),
            px(_TRACK_H),
        )
        off, on = QColor(palette.border_strong), QColor(palette.accent)
        mix = self._position
        fill = QColor(
            round(off.red() + (on.red() - off.red()) * mix),
            round(off.green() + (on.green() - off.green()) * mix),
            round(off.blue() + (on.blue() - off.blue()) * mix),
        )
        if not self.isEnabled():
            fill = QColor(palette.surface_active)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob = track.height() - 2 * px(_KNOB_GAP) + 2
        left = track.left() + px(_KNOB_GAP) - 1
        travel = track.width() - knob - 2 * (px(_KNOB_GAP) - 1)
        painter.setBrush(QColor(palette.fg_faint if not self.isEnabled() else "#ffffff"))
        painter.drawEllipse(
            QPointF(left + travel * mix + knob / 2, track.center().y()), knob / 2, knob / 2
        )
        if self.hasFocus() and self._keyboard_focus:
            ring = QPen(QColor(palette.border_focus), max(px(2), 2))
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            outer = track.adjusted(-px(2), -px(2), px(2), px(2))
            painter.drawRoundedRect(outer, outer.height() / 2, outer.height() / 2)
        event.accept()


class SwitchRow(QWidget):
    """Label and hint on the left, the switch on the right; clicking the text toggles too."""

    toggled = Signal(bool)

    def __init__(
        self,
        kit: UiKit,
        label: str,
        hint: str = "",
        *,
        checked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.switch = Switch(kit, checked=checked)
        self._label = QLabel(label)
        self._hint = QLabel(hint)
        set_role(self._hint, "muted")
        self._hint.setWordWrap(True)
        self._hint.setVisible(bool(hint))
        self._texts = QVBoxLayout()
        self._texts.setContentsMargins(0, 0, 0, 0)
        self._texts.addWidget(self._label)
        self._texts.addWidget(self._hint)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.addLayout(self._texts, 1)
        self._row.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)
        self.switch.setAccessibleName(label)
        self.switch.toggled.connect(self.toggled)
        bind_kit(kit, zoom=self._restyle)
        self._restyle()

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.switch.setChecked(checked)

    def set_texts(self, label: str, hint: str = "") -> None:
        self._label.setText(label)
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))
        self.switch.setAccessibleName(label)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.switch.isEnabled():
            self.switch.toggle()
        super().mouseReleaseEvent(event)

    def _restyle(self) -> None:
        self._texts.setSpacing(self.kit.px(SPACE[1]))
        self._row.setSpacing(self.kit.px(SPACE[6]))
