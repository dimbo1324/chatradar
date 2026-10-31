"""Labels: a role-styled factory and a label that elides instead of forcing the layout wider."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

from chatimport.gui.widgets.base import set_role

if TYPE_CHECKING:
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtWidgets import QWidget


def make_label(
    text: str = "",
    role: str | None = None,
    *,
    wrap: bool = False,
    selectable: bool = False,
    parent: QWidget | None = None,
) -> QLabel:
    label = QLabel(text, parent)
    if role is not None:
        set_role(label, role)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ElidedLabel(QLabel):
    """Single-line label that ends with an ellipsis when narrow and tooltips the full text."""

    def __init__(
        self,
        text: str = "",
        role: str | None = None,
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self._custom_tip = False
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if role is not None:
            set_role(self, role)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self._refit()

    def full_text(self) -> str:
        return self._full

    def setToolTip(self, text: str) -> None:
        self._custom_tip = bool(text)
        super().setToolTip(text)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        margins = self.contentsMargins()
        return QSize(
            metrics.horizontalAdvance(self._full) + margins.left() + margins.right() + 2,
            metrics.height() + margins.top() + margins.bottom(),
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.sizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refit()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._refit()

    def _refit(self) -> None:
        width = max(self.contentsRect().width(), 0)
        shown = (
            self.fontMetrics().elidedText(self._full, self._mode, width) if width else self._full
        )
        if shown != self.text():
            super().setText(shown)
        if not self._custom_tip:
            super().setToolTip(self._full if shown != self._full else "")
