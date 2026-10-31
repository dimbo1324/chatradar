"""Page-level containers: a bordered card and a page header (title, lede, trailing actions)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLayout, QWidget

    from chatimport.gui.kit import UiKit


class Card(QFrame):
    """A raised, bordered surface; fill `body` (a vertical layout) with content."""

    def __init__(
        self, kit: UiKit, *, padding: int = SPACE[6], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self._padding = padding
        set_role(self, "card")
        self.body = QVBoxLayout(self)
        bind_kit(kit, zoom=self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        pad = self.kit.px(self._padding)
        self.body.setContentsMargins(pad, pad, pad, pad)
        self.body.setSpacing(self.kit.px(SPACE[4]))


class PageHeader(QFrame):
    def __init__(
        self,
        kit: UiKit,
        title: str,
        lede: str = "",
        *,
        trailing: QLayout | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self._title = QLabel(title)
        set_role(self._title, "title")
        self._lede = QLabel(lede)
        set_role(self._lede, "muted")
        self._lede.setWordWrap(True)
        self._lede.setVisible(bool(lede))
        self._texts = QVBoxLayout()
        self._texts.setContentsMargins(0, 0, 0, 0)
        self._texts.addWidget(self._title)
        self._texts.addWidget(self._lede)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.addLayout(self._texts, 1)
        if trailing is not None:
            self._row.addLayout(trailing)
            self._row.setAlignment(trailing, Qt.AlignmentFlag.AlignTop)
        bind_kit(kit, zoom=self._restyle)
        self._restyle()

    def set_texts(self, title: str, lede: str = "") -> None:
        self._title.setText(title)
        self._lede.setText(lede)
        self._lede.setVisible(bool(lede))

    def _restyle(self) -> None:
        self._texts.setSpacing(self.kit.px(SPACE[2]))
        self._row.setSpacing(self.kit.px(SPACE[6]))
