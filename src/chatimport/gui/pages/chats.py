"""Stub of the Chats page; the real page replaces this module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from chatimport.gui.widgets.empty_state import EmptyState

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext


class ChatsPage(QWidget):
    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.addWidget(EmptyState(gui.kit, "chats", "Chats (stub)"))
