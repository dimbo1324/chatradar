"""The window's own preferences: language, theme, zoom, layout and freshness thresholds.

Stored as one small JSON file next to the config (never in the data root). Anything unreadable
or out of range falls back to the default for that field, so a damaged file can never keep the
window from opening; it is only preferences, not archive data.
"""

from __future__ import annotations

import json
import locale
from dataclasses import asdict, dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from chatimport.gui.format import FreshnessThresholds
from chatimport.gui.strings import LANGUAGES, Language
from chatimport.gui.tokens import ZOOM_MAX, ZOOM_MIN
from chatimport.storage.fileio import atomic_write_bytes

if TYPE_CHECKING:
    from pathlib import Path

type ThemePreference = Literal["light", "dark", "system"]

THEME_PREFERENCES: Final[tuple[ThemePreference, ...]] = ("light", "dark", "system")
SETTINGS_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class WindowGeometry:
    x: int
    y: int
    width: int
    height: int
    maximized: bool = False


def system_language() -> Language:
    name = (locale.getlocale()[0] or "").lower()
    return "ru" if name.startswith(("ru", "russian")) else "en"


@dataclass(frozen=True, slots=True)
class GuiSettings:
    language: Language = field(default_factory=system_language)
    theme: ThemePreference = "system"
    zoom: float | None = None
    sidebar_collapsed: bool = False
    close_to_tray: bool = True
    start_hidden: bool = False
    last_page: str = "overview"
    chats_absolute_time: bool = False
    geometry: WindowGeometry | None = None
    freshness: FreshnessThresholds = field(default_factory=FreshnessThresholds)
    freshness_per_chat: dict[str, FreshnessThresholds] = field(
        default_factory=dict[str, FreshnessThresholds]
    )

    def thresholds_for(self, chat_id: int | str) -> FreshnessThresholds:
        return self.freshness_per_chat.get(str(chat_id), self.freshness)


def _as_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _thresholds(raw: Any, default: FreshnessThresholds) -> FreshnessThresholds:
    if not isinstance(raw, dict):
        return default
    data = cast("dict[str, Any]", raw)
    parsed = FreshnessThresholds(
        fresh_below=_as_int(data.get("fresh_below"), default.fresh_below),
        recent_below=_as_int(data.get("recent_below"), default.recent_below),
        stale_below=_as_int(data.get("stale_below"), default.stale_below),
    )
    return parsed if parsed.is_ordered() else default


def _geometry(raw: Any) -> WindowGeometry | None:
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, Any]", raw)
    try:
        width, height = int(data["width"]), int(data["height"])
        x, y = int(data["x"]), int(data["y"])
    except KeyError, TypeError, ValueError:
        return None
    if width < 200 or height < 150:
        return None
    return WindowGeometry(x, y, width, height, maximized=data.get("maximized") is True)


def _zoom(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return min(max(float(raw), ZOOM_MIN), ZOOM_MAX)


def settings_from_json(raw: Any) -> GuiSettings:
    defaults = GuiSettings()
    if not isinstance(raw, dict):
        return defaults
    data = cast("dict[str, Any]", raw)
    language = data.get("language")
    theme = data.get("theme")
    last_page = data.get("last_page")
    per_chat_raw = data.get("freshness_per_chat")
    per_chat: dict[str, FreshnessThresholds] = {}
    if isinstance(per_chat_raw, dict):
        for key, value in cast("dict[str, Any]", per_chat_raw).items():
            per_chat[str(key)] = _thresholds(value, defaults.freshness)
    return GuiSettings(
        language=language if language in LANGUAGES else defaults.language,
        theme=theme if theme in THEME_PREFERENCES else defaults.theme,
        zoom=_zoom(data.get("zoom")),
        sidebar_collapsed=data.get("sidebar_collapsed") is True,
        close_to_tray=data.get("close_to_tray") is not False,
        start_hidden=data.get("start_hidden") is True,
        last_page=last_page if isinstance(last_page, str) else defaults.last_page,
        chats_absolute_time=data.get("chats_absolute_time") is True,
        geometry=_geometry(data.get("geometry")),
        freshness=_thresholds(data.get("freshness"), defaults.freshness),
        freshness_per_chat=per_chat,
    )


class GuiSettingsStore:
    """Load once, then `update(...)` replaces fields and writes the file atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._settings = self._load()

    @property
    def settings(self) -> GuiSettings:
        return self._settings

    def _load(self) -> GuiSettings:
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return GuiSettings()
        return settings_from_json(raw)

    def update(self, **changes: Any) -> GuiSettings:
        self._settings = replace(self._settings, **changes)
        self.save()
        return self._settings

    def save(self) -> None:
        payload = {"v": SETTINGS_VERSION, **asdict(self._settings)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        atomic_write_bytes(self.path, text.encode("utf-8"))
