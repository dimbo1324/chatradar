"""Stub of the placeholder page for sections that arrive later; the real page replaces this."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from chatimport.gui.widgets.empty_state import EmptyState

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext


class PlaceholderPage(QWidget):
    def __init__(self, gui: GuiContext, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.addWidget(EmptyState(gui.kit, key, f"{key} (stub)"))
