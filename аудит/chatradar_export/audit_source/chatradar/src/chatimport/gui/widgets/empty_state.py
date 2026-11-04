"""The "nothing here" block: large faint icon, title, explanation, optional action button."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit

_MAX_TEXT_CHARS = 52


class EmptyState(QFrame):
    def __init__(
        self,
        kit: UiKit,
        icon_name: str,
        title: str,
        text: str = "",
        *,
        action: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("EmptyState")
        self._icon_name = icon_name
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel(title)
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._text = QLabel(text)
        self._text.setObjectName("EmptyText")
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text.setWordWrap(True)
        self._text.setVisible(bool(text))
        self._column = QVBoxLayout(self)
        self._column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for part in (self._icon, self._title, self._text):
            self._column.addWidget(part, 0, Qt.AlignmentFlag.AlignHCenter)
        if action is not None:
            self._column.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setAccessibleName(title)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle)
        self._restyle()

    def set_icon(self, name: str) -> None:
        self._icon_name = name
        self._restyle()

    def set_texts(self, title: str, text: str = "") -> None:
        self._title.setText(title)
        self._text.setText(text)
        self._text.setVisible(bool(text))
        self.setAccessibleName(title)

    def _restyle(self) -> None:
        px = self.kit.px
        self._column.setContentsMargins(px(SPACE[6]), px(SPACE[10]), px(SPACE[6]), px(SPACE[10]))
        self._column.setSpacing(px(SPACE[4]))
        self._icon.setPixmap(
            icon_pixmap(self._icon_name, self.kit.palette.fg_faint, px(LAYOUT["icon_xl"]), 1.4)
        )
        self._text.setMaximumWidth(px(_MAX_TEXT_CHARS * 7))
