"""The base of every card on the Data page: an icon, a title, a lede and a busy stripe."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from chatimport.gui.i18n import tr
from chatimport.gui.icons import icon_pixmap
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.card import Card
from chatimport.gui.widgets.progress import BusyStripe

if TYPE_CHECKING:
    from PySide6.QtWidgets import QLayout, QWidget

    from chatimport.gui.pages.data_common import DataEnv


class Section(Card):
    """A card with a header (icon, title, lede, trailing buttons) and a stripe that runs while busy.

    Subclasses fill `content` and implement `retranslate`; the title and lede keys are
    `data.<name>.title` and `data.<name>.lede`.
    """

    def __init__(
        self,
        env: DataEnv,
        name: str,
        icon_name: str,
        *,
        trailing: QLayout | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(env.gui.kit, parent=parent)
        self.env = env
        self.kit = env.gui.kit
        self._name = name
        self._icon_name = icon_name
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel()
        set_role(self._title, "section")
        self._lede = QLabel()
        set_role(self._lede, "muted")
        self._lede.setWordWrap(True)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(self.kit.px(SPACE[1]))
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(self.kit.px(SPACE[3]))
        title_row.addWidget(self._icon)
        title_row.addWidget(self._title, 1)
        texts.addLayout(title_row)
        texts.addWidget(self._lede)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addLayout(texts, 1)
        if trailing is not None:
            head.addLayout(trailing)
            head.setAlignment(trailing, Qt.AlignmentFlag.AlignTop)
        self.stripe = BusyStripe(self.kit)
        self.body.addLayout(head)
        self.body.addWidget(self.stripe)
        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(self.content)
        bind_kit(self.kit, theme=self._paint_icon, zoom=self._paint_icon, language=self._retitle)
        self._paint_icon()
        self._set_title()

    def set_busy(self, busy: bool) -> None:
        self.stripe.set_active(busy)

    def retranslate(self) -> None:
        """Re-set the texts that depend on the language; subclasses also call it once when built."""

    def _set_title(self) -> None:
        self._title.setText(tr(f"data.{self._name}.title"))
        self._lede.setText(tr(f"data.{self._name}.lede"))
        self.setAccessibleName(self._title.text())

    def _retitle(self) -> None:
        self._set_title()
        self.retranslate()

    def _paint_icon(self) -> None:
        size = self.kit.px(LAYOUT["icon_lg"])
        self._icon.setFixedSize(QSize(size, size))
        self._icon.setPixmap(icon_pixmap(self._icon_name, self.kit.palette.accent, size))
