"""A small status pill: tone colour, optional leading icon or dot, text that never wraps."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import Tone, bind_kit, set_property

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from chatimport.gui.kit import UiKit

DOT_SIZE: Final = 7


class Dot(QWidget):
    """A filled circle in a tone's foreground colour (a "live" or "error" marker)."""

    def __init__(self, kit: UiKit, tone: Tone = "live", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self._tone: Tone = tone
        bind_kit(kit, theme=self.update, zoom=self._resize)
        self._resize()

    def set_tone(self, tone: Tone) -> None:
        self._tone = tone
        self.update()

    def _resize(self) -> None:
        side = self.kit.px(DOT_SIZE)
        self.setFixedSize(QSize(side, side))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tone_colors(self.kit.palette, self._tone)[2]))
        painter.drawEllipse(QRectF(self.rect()))
        event.accept()


class Chip(QFrame):
    def __init__(
        self,
        kit: UiKit,
        text: str = "",
        tone: Tone = "neutral",
        *,
        icon_name: str | None = None,
        dot: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("Chip")
        self._tone: Tone = tone
        self._icon_name = icon_name
        self.setProperty("tone", tone)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._layout = QHBoxLayout(self)
        self._icon = QLabel()
        self._icon.setVisible(icon_name is not None)
        self._dot = Dot(kit, tone)
        self._dot.setVisible(dot)
        self._text = QLabel(text)
        for part in (self._dot, self._icon, self._text):
            self._layout.addWidget(part)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle)
        self._restyle()

    @property
    def text(self) -> str:
        return self._text.text()

    def set_text(self, text: str) -> None:
        self._text.setText(text)

    def set_tone(self, tone: Tone) -> None:
        self._tone = tone
        self._dot.set_tone(tone)
        set_property(self, "tone", tone)
        self._restyle()

    def set_icon(self, name: str | None) -> None:
        self._icon_name = name
        self._restyle()

    def set_dot(self, visible: bool) -> None:
        self._dot.setVisible(visible)

    def _restyle(self) -> None:
        px = self.kit.px
        self._layout.setContentsMargins(px(SPACE[4]), px(SPACE[1]), px(SPACE[4]), px(SPACE[1]))
        self._layout.setSpacing(px(SPACE[2] + 1))
        self.setFixedHeight(px(LAYOUT["icon_lg"] + 2))
        if self._icon_name is not None:
            color = tone_colors(self.kit.palette, self._tone)[2]
            size = px(LAYOUT["icon_sm"])
            self._icon.setPixmap(icon_pixmap(self._icon_name, color, size))
        self._icon.setVisible(self._icon_name is not None)
