"""Light, dark or follow-the-system theme, applied as one application stylesheet.

`ThemeManager` resolves the preference (asking the OS through Qt's style hints), builds the QSS
for the current palette and zoom, applies it, and emits `changed`. Zoom changes rebuild the
stylesheet too, and the manager is created after the zoom manager so its slot runs before any
widget's own zoom handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from chatimport.gui.format import Freshness
from chatimport.gui.stylesheet import build_stylesheet
from chatimport.gui.tokens import DARK, PALETTES, Palette

if TYPE_CHECKING:
    from collections.abc import Callable

    from chatimport.gui.settings import ThemePreference
    from chatimport.gui.zoom import ZoomManager

type ThemeName = Literal["light", "dark"]

__all__ = [
    "ThemeManager",
    "ThemeName",
    "build_stylesheet",
    "freshness_color",
    "qt_palette",
    "system_theme",
]


def system_theme() -> ThemeName:
    hints = QGuiApplication.styleHints()
    return "dark" if hints.colorScheme() == Qt.ColorScheme.Dark else "light"


def freshness_color(palette: Palette, level: Freshness) -> str:
    return {
        Freshness.FRESH: palette.live,
        Freshness.RECENT: palette.fg_secondary,
        Freshness.STALE: palette.warning,
        Freshness.DORMANT: palette.fg_faint,
        Freshness.UNKNOWN: palette.fg_faint,
    }[level]


def qt_palette(palette: Palette) -> QPalette:
    """The `QPalette` behind native-drawn parts (arrows, selection, disabled text)."""
    result = QPalette()
    roles = {
        QPalette.ColorRole.Window: palette.canvas,
        QPalette.ColorRole.WindowText: palette.fg,
        QPalette.ColorRole.Base: palette.surface,
        QPalette.ColorRole.AlternateBase: palette.surface_sunken,
        QPalette.ColorRole.Text: palette.fg,
        QPalette.ColorRole.Button: palette.surface,
        QPalette.ColorRole.ButtonText: palette.fg_secondary,
        QPalette.ColorRole.ToolTipBase: palette.surface_raised,
        QPalette.ColorRole.ToolTipText: palette.fg,
        QPalette.ColorRole.Highlight: palette.selection,
        QPalette.ColorRole.HighlightedText: palette.fg,
        QPalette.ColorRole.PlaceholderText: palette.fg_faint,
        QPalette.ColorRole.Link: palette.accent,
    }
    for role, color in roles.items():
        result.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(palette.fg_faint))
    return result


class ThemeManager(QObject):
    changed = Signal()

    def __init__(
        self,
        zoom: ZoomManager,
        preference: ThemePreference = "system",
        *,
        app: QApplication | None = None,
        detect_system: Callable[[], ThemeName] = system_theme,
    ) -> None:
        super().__init__()
        self._zoom = zoom
        self._preference: ThemePreference = preference
        self._detect_system = detect_system
        self._app = app
        self._resolved: ThemeName = self._resolve()
        zoom.changed.connect(self._on_zoom)
        if app is not None:
            QApplication.setStyle(QStyleFactory.create("Fusion"))
            app.styleHints().colorSchemeChanged.connect(self._on_system_changed)
            self._apply()

    @property
    def preference(self) -> ThemePreference:
        return self._preference

    @property
    def resolved(self) -> ThemeName:
        return self._resolved

    @property
    def palette(self) -> Palette:
        return PALETTES[self._resolved]

    @property
    def is_dark(self) -> bool:
        return self.palette is DARK

    def set_preference(self, preference: ThemePreference) -> None:
        if preference == self._preference:
            return
        self._preference = preference
        self._refresh()

    def stylesheet(self) -> str:
        return build_stylesheet(self.palette, self._zoom.factor)

    def _resolve(self) -> ThemeName:
        if self._preference == "system":
            return self._detect_system()
        return "dark" if self._preference == "dark" else "light"

    def _refresh(self) -> None:
        self._resolved = self._resolve()
        self._apply()
        self.changed.emit()

    def _apply(self) -> None:
        if self._app is None:
            return
        self._app.setPalette(qt_palette(self.palette))
        self._app.setStyleSheet(self.stylesheet())

    def _on_zoom(self, _factor: float) -> None:
        self._apply()

    def _on_system_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self._preference == "system" and self._resolve() != self._resolved:
            self._refresh()
