"""A tinted explanation block: icon, optional bold title, wrapping body, optional action."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import TONE_ICONS, Tone, bind_kit, set_property

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit


class Callout(QFrame):
    def __init__(
        self,
        kit: UiKit,
        tone: Tone,
        body: str,
        *,
        title: str = "",
        action: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("Callout")
        self._tone: Tone = tone
        self.setProperty("tone", tone)
        self._icon = QLabel()
        self._icon.setObjectName("CalloutIcon")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title = QLabel(title)
        self._title.setObjectName("CalloutTitle")
        self._title.setWordWrap(True)
        self._title.setVisible(bool(title))
        self._body = QLabel(body)
        self._body.setObjectName("CalloutBody")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._text = QVBoxLayout()
        self._text.setContentsMargins(0, 0, 0, 0)
        self._text.addWidget(self._title)
        self._text.addWidget(self._body)
        self._row = QHBoxLayout(self)
        self._row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        self._row.addLayout(self._text, 1)
        if action is not None:
            self._row.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setAccessibleName(title or body)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle)
        self._restyle()

    def set_tone(self, tone: Tone) -> None:
        self._tone = tone
        set_property(self, "tone", tone)
        set_property(self._icon, "tone", tone)
        self._restyle()

    def set_body(self, body: str) -> None:
        self._body.setText(body)

    def set_title(self, title: str) -> None:
        self._title.setText(title)
        self._title.setVisible(bool(title))

    def _restyle(self) -> None:
        px = self.kit.px
        self._row.setContentsMargins(px(SPACE[5]), px(SPACE[5]), px(SPACE[5]), px(SPACE[5]))
        self._row.setSpacing(px(SPACE[4]))
        self._text.setSpacing(px(SPACE[1]))
        color = tone_colors(self.kit.palette, self._tone)[2]
        size = px(LAYOUT["icon_md"])
        self._icon.setPixmap(icon_pixmap(TONE_ICONS[self._tone], color, size))
        self._icon.setFixedWidth(size)
