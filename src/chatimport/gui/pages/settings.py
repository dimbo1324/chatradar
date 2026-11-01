"""Placeholder for the settings page; replaced by the real page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport.gui.pages.placeholder import PlaceholderPage

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.context import GuiContext


class SettingsPage(PlaceholderPage):
    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(gui, "settings", parent)
