"""The window's pages, keyed by the sidebar entry they belong to."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport.gui.pages.chats import ChatsPage
from chatimport.gui.pages.data import DataPage
from chatimport.gui.pages.log import LogPage
from chatimport.gui.pages.overview import OverviewPage
from chatimport.gui.pages.settings import SettingsPage

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.context import GuiContext

PAGE_KEYS = ("overview", "chats", "log", "data", "settings")


def build_pages(gui: GuiContext) -> dict[str, QWidget]:
    return {
        "overview": OverviewPage(gui),
        "chats": ChatsPage(gui),
        "log": LogPage(gui),
        "data": DataPage(gui),
        "settings": SettingsPage(gui),
    }
