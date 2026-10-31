"""A search box: leading icon, clear button, debounced query signal, Esc clears."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLineEdit

from chatimport.gui.i18n import tr
from chatimport.gui.icons import icon
from chatimport.gui.tokens import LAYOUT
from chatimport.gui.widgets.base import bind_kit

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit

DEBOUNCE_MS: Final = 150


class SearchField(QLineEdit):
    """`query_changed` fires after typing pauses; `text()` is always the live value."""

    query_changed = Signal(str)

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self._lead = QAction(self)
        self._clear = QAction(self)
        self.addAction(self._lead, QLineEdit.ActionPosition.LeadingPosition)
        self.addAction(self._clear, QLineEdit.ActionPosition.TrailingPosition)
        self._clear.setVisible(False)
        self._clear.triggered.connect(self.clear)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._emit)
        self.textChanged.connect(self._on_text)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()

    def _on_text(self, text: str) -> None:
        self._clear.setVisible(bool(text))
        self._timer.start()

    def _emit(self) -> None:
        self.query_changed.emit(self.text())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
            event.accept()
            return
        super().keyPressEvent(event)

    def _retranslate(self) -> None:
        self.setPlaceholderText(tr("search.placeholder"))
        self._clear.setToolTip(tr("search.clear"))
        self.setAccessibleName(tr("search.placeholder"))

    def _restyle(self) -> None:
        palette = self.kit.palette
        size = self.kit.px(LAYOUT["icon_md"])
        self._lead.setIcon(icon("search", palette.fg_faint, size))
        self._clear.setIcon(icon("x", palette.fg_muted, size))
        self.setFixedHeight(self.kit.px(LAYOUT["control"]))
