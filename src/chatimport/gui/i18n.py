"""Runtime language switching: `tr(key, **params)` and `plural(n, key)` read the live language.

`LanguageManager.changed` fires after the switch, and every widget retranslates itself from it,
so the window never needs a restart. The catalogue itself lives in `strings` (Qt-free).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from chatimport.gui import strings
from chatimport.gui.strings import (
    LANGUAGES,
    Language,
    LocaleDriftError,
    check_drift,
    register_strings,
)

__all__ = [
    "LANGUAGES",
    "Language",
    "LanguageManager",
    "LocaleDriftError",
    "check_drift",
    "plural",
    "register_strings",
    "tr",
]


def tr(key: str, **params: object) -> str:
    return strings.translate(strings.current_language(), key, **params)


def plural(count: int, key: str, **params: object) -> str:
    """The plural form of `key` for `count`; `{n}` in the text is the count itself."""
    return strings.translate_plural(strings.current_language(), count, key, **params)


class LanguageManager(QObject):
    changed = Signal(str)

    def __init__(self, language: Language = "en") -> None:
        super().__init__()
        strings.set_current_language(language)
        check_drift()

    @property
    def current(self) -> Language:
        return strings.current_language()

    def set_language(self, language: Language) -> None:
        if language == strings.current_language() or language not in LANGUAGES:
            return
        strings.set_current_language(language)
        self.changed.emit(language)
