"""`UiKit`: the three managers every widget listens to, and the factory that wires persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chatimport.gui.i18n import LanguageManager
from chatimport.gui.theme import ThemeManager
from chatimport.gui.zoom import ZoomManager, screen_auto_factor

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from chatimport.gui.settings import GuiSettingsStore
    from chatimport.gui.tokens import Palette


@dataclass(frozen=True, slots=True)
class UiKit:
    theme: ThemeManager
    language: LanguageManager
    zoom: ZoomManager

    @property
    def palette(self) -> Palette:
        return self.theme.palette

    def px(self, pixels: float) -> int:
        return self.zoom.scaled(pixels)


def build_kit(store: GuiSettingsStore, app: QApplication | None) -> UiKit:
    """Managers from the stored preferences; every later change is written back to `store`."""
    settings = store.settings
    zoom = ZoomManager(settings.zoom, screen_auto_factor() if app is not None else 1.0)
    theme = ThemeManager(zoom, settings.theme, app=app)
    language = LanguageManager(settings.language)

    def save_zoom(_factor: float) -> None:
        store.update(zoom=zoom.stored)

    def save_theme() -> None:
        store.update(theme=theme.preference)

    def save_language(name: str) -> None:
        store.update(language=name)

    zoom.changed.connect(save_zoom)
    theme.changed.connect(save_theme)
    language.changed.connect(save_language)
    return UiKit(theme=theme, language=language, zoom=zoom)
