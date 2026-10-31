"""Shared widget plumbing: listening to the managers and re-polishing after property changes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit

type Tone = Literal["neutral", "muted", "accent", "live", "success", "warning", "danger", "info"]

KEYBOARD_REASONS: Final = (
    Qt.FocusReason.TabFocusReason,
    Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
)

TONE_ICONS: Final[dict[str, str]] = {
    "neutral": "info",
    "muted": "info",
    "accent": "info",
    "info": "info",
    "live": "radio",
    "success": "check-circle",
    "warning": "alert",
    "danger": "x-circle",
}


def bind_kit(
    kit: UiKit,
    *,
    theme: Callable[[], object] | None = None,
    zoom: Callable[[], object] | None = None,
    language: Callable[[], object] | None = None,
) -> None:
    """Call the given handlers when the theme, zoom or language changes.

    Handlers are bound methods of the widget, so Qt drops the connection with the widget.
    The application stylesheet already re-polishes standard widgets; the handlers exist for
    what is painted or sized by hand.
    """
    if theme is not None:
        kit.theme.changed.connect(theme)
    if zoom is not None:
        kit.zoom.changed.connect(zoom)
    if language is not None:
        kit.language.changed.connect(language)


def set_property(widget: QWidget, name: str, value: object) -> None:
    """Set a dynamic property that a QSS selector reads, and re-evaluate the widget's style."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_role(widget: QWidget, role: str) -> None:
    """Pick a QSS text or surface role (`muted`, `caption`, `title`, `card`, ...)."""
    set_property(widget, "role", role)
