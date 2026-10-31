"""One number with its name, an optional icon and hint: the Overview's building block."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import Tone, bind_kit, set_property
from chatimport.gui.widgets.labels import ElidedLabel

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit


class StatCard(QFrame):
    def __init__(
        self,
        kit: UiKit,
        label: str,
        value: str = "",
        *,
        hint: str = "",
        icon_name: str | None = None,
        tone: Tone = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("StatCard")
        self._tone: Tone = tone
        self._icon_name = icon_name
        self.setProperty("tone", tone)
        self._icon = QLabel()
        self._icon.setVisible(icon_name is not None)
        self._label = ElidedLabel(label)
        self._label.setObjectName("StatLabel")
        self._value = QLabel(value)
        self._value.setObjectName("StatValue")
        self._hint = ElidedLabel(hint)
        self._hint.setObjectName("StatHint")
        self._hint.setVisible(bool(hint))
        self._head = QHBoxLayout()
        self._head.addWidget(self._icon)
        self._head.addWidget(self._label, 1)
        self._column = QVBoxLayout(self)
        self._column.addLayout(self._head)
        self._column.addWidget(self._value)
        self._column.addWidget(self._hint)
        self._sync_name()
        bind_kit(kit, theme=self._restyle, zoom=self._restyle)
        self._restyle()

    def set_label(self, text: str) -> None:
        self._label.setText(text)
        self._sync_name()

    def set_value(self, text: str) -> None:
        self._value.setText(text)
        self._sync_name()

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)
        self._hint.setVisible(bool(text))

    def set_tone(self, tone: Tone) -> None:
        self._tone = tone
        set_property(self, "tone", tone)
        self._restyle()

    def _sync_name(self) -> None:
        self.setAccessibleName(f"{self._label.full_text()}: {self._value.text()}")

    def _restyle(self) -> None:
        px = self.kit.px
        self._column.setContentsMargins(px(SPACE[6]), px(SPACE[5]), px(SPACE[6]), px(SPACE[5]))
        self._column.setSpacing(px(SPACE[2]))
        self._head.setSpacing(px(SPACE[3]))
        if self._icon_name is not None:
            _bg, _border, color = tone_colors(self.kit.palette, self._tone)
            if self._tone == "neutral":
                color = self.kit.palette.fg_muted
            self._icon.setPixmap(icon_pixmap(self._icon_name, color, px(LAYOUT["icon_md"] - 2)))
