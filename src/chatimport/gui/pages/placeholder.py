"""A "coming soon" page for a section that is not built yet (Log, Data, Settings)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.locales import placeholder as _placeholder_strings
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.empty_state import EmptyState

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext

_ = _placeholder_strings

ICONS = {"log": "log", "data": "data", "settings": "settings"}


class PlaceholderPage(QWidget):
    subtitle_key = "placeholder.subtitle"

    def __init__(self, gui: GuiContext, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        self.key = key
        self.title_key = f"nav.{key}"
        self._state = EmptyState(gui.kit, ICONS.get(key, "info"), "", "")
        column = QVBoxLayout(self)
        column.addWidget(self._state)
        bind_kit(gui.kit, language=self._retranslate)
        self._retranslate()

    def _retranslate(self) -> None:
        page = tr(self.title_key)
        self._state.set_texts(
            tr("placeholder.title", page=page), tr(f"placeholder.{self.key}.text")
        )
