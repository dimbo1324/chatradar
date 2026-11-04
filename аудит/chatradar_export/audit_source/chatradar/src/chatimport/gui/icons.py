"""A hand-drawn 24x24 stroke icon set kept as path data, rendered to `QIcon`/`QPixmap` on demand.

Every path is geometry only; the colour and stroke weight are applied when rendering, so one
set serves both palettes. Rendering goes through `QSvgRenderer` and is cached per
(name, colour, size, weight, density).
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

DEFAULT_WEIGHT: Final = 1.7

ICON_PATHS: Final[dict[str, str]] = {
    "home": "M4 11l8-7 8 7 M6 9.5V20h12V9.5 M10 20v-6h4v6",
    "chats": "M5 4h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H10l-5 4V5a1 1 0 0 1 1-1Z M8 9h8 M8 12.5h5",
    "log": "M8 6h12 M8 12h12 M8 18h12 M4 6h.01 M4 12h.01 M4 18h.01",
    "data": (
        "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Z M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6 "
        "M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"
    ),
    "settings": "M4 7h9 M17 7h3 M4 17h3 M11 17h9 M15 4v6 M7 14v6",
    "sliders": "M4 7h9 M17 7h3 M4 17h3 M11 17h9 M15 4v6 M7 14v6",
    "folder": "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z",
    "folder-open": "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H3Z M3 10h18l-2 8H5Z",
    "shield": "M12 3l8 3v6c0 4.5-3.2 8.3-8 9.5C7.2 20.3 4 16.5 4 12V6Z",
    "shield-check": "M12 3l8 3v6c0 4.5-3.2 8.3-8 9.5C7.2 20.3 4 16.5 4 12V6Z M8.5 12l2.5 2.5 4.5-5",
    "lock": "M5 11h14v9H5Z M8 11V8a4 4 0 0 1 8 0v3",
    "play": "M7 5l12 7-12 7Z",
    "pause": "M8 5v14 M16 5v14",
    "stop": "M7 7h10v10H7Z",
    "check": "M4 12.5l5 5L20 6.5",
    "check-circle": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M8 12l3 3 5-5",
    "x-circle": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M9 9l6 6 M15 9l-6 6",
    "ban": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M5.6 5.6l12.8 12.8",
    "clock": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 7v5l3 2",
    "hourglass": "M7 3h10 M7 21h10 M8 3v3.5L12 12l-4 5.5V21 M16 3v3.5L12 12l4 5.5V21",
    "calendar": "M4 6h16v14H4Z M4 10h16 M8 3v4 M16 3v4",
    "chart": "M4 20V4 M4 20h16 M8 16v-5 M13 16V8 M18 16v-3",
    "activity": "M3 12h4l3 8 4-16 3 8h4",
    "sun": (
        "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 "
        "M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4"
    ),
    "moon": "M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z",
    "monitor": "M3 5h18v11H3Z M9 20h6 M12 16v4",
    "globe": (
        "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M3 12h18 "
        "M12 3c2.5 2.6 3.8 5.7 3.8 9S14.5 18.4 12 21c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3Z"
    ),
    "chevron": "M9 6l6 6-6 6",
    "chevron-left": "M15 6l-6 6 6 6",
    "chevron-down": "M6 9l6 6 6-6",
    "chevron-up": "M6 15l6-6 6 6",
    "arrow-up": "M12 19V5 M6 11l6-6 6 6",
    "arrow-down": "M12 5v14 M6 13l6 6 6-6",
    "panel-left": "M4 5h16v14H4Z M9 5v14",
    "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z M16.5 16.5L21 21",
    "x": "M6 6l12 12 M18 6L6 18",
    "plus": "M12 5v14 M5 12h14",
    "minus": "M5 12h14",
    "copy": "M9 9h10v10H9Z M15 9V5H5v10h4",
    "external": "M14 4h6v6 M20 4l-8 8 M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
    "refresh": "M20 12a8 8 0 1 1-2.6-5.9 M20 4v4h-4",
    "alert": "M12 4l9 16H3Z M12 10v4 M12 17.5v.5",
    "info": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z M12 11v5 M12 7.5v.5",
    "file": "M6 3h7l5 5v13H6Z M13 3v5h5",
    "eye": "M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
    "download": "M12 4v11 M8 11l4 4 4-4 M4 19h16",
    "upload": "M12 20V9 M8 13l4-4 4 4 M4 5h16",
    "filter": "M3 5h18l-7 8v6l-4 2v-8Z",
    "disk": "M3 14h18 M5 14l2-8h10l2 8v5H3v-5Z M7 17h.01 M11 17h.01",
    "send": "M21 3L3 10.5l7 3 3 7Z M21 3L10 13.5",
    "radio": (
        "M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z M8.5 8.5a5 5 0 0 0 0 7 M15.5 8.5a5 5 0 0 1 0 7 "
        "M5.6 5.6a9 9 0 0 0 0 12.8 M18.4 5.6a9 9 0 0 1 0 12.8"
    ),
    "bell": "M6 16V11a6 6 0 0 1 12 0v5l2 2H4Z M10 21h4",
    "trash": "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13 M10 11v6 M14 11v6",
    "hash": "M5 9h14 M5 15h14 M10 4L8 20 M16 4l-2 16",
    "user": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z M4 20c0-4 3.6-6 8-6s8 2 8 6",
    "users": (
        "M9 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z M2.5 20c0-3.6 2.9-5.5 6.5-5.5s6.5 1.9 6.5 5.5 "
        "M16 5.5a3.5 3.5 0 0 1 0 7 M18.5 14.8c1.8.7 3 2.2 3 5.2"
    ),
    "package": "M12 3l8 4.5v9L12 21l-8-4.5v-9Z M4 7.5l8 4.5 8-4.5 M12 12v9",
}


def _svg(path: str, color: str, weight: float) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{weight}" stroke-linecap="round" '
        f'stroke-linejoin="round"><path d="{path}"/></svg>'
    ).encode()


def _pixel_density() -> int:
    screen = QGuiApplication.primaryScreen()
    return max(2, math.ceil(screen.devicePixelRatio())) if screen else 2


@lru_cache(maxsize=1024)
def _cached_pixmap(name: str, color: str, size: int, weight: float, density: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(ICON_PATHS[name], color, weight)))
    pixmap = QPixmap(size * density, size * density)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size * density, size * density))
    painter.end()
    pixmap.setDevicePixelRatio(density)
    return pixmap


def icon_pixmap(name: str, color: str, size: int = 16, weight: float = DEFAULT_WEIGHT) -> QPixmap:
    return _cached_pixmap(name, color, max(size, 1), weight, _pixel_density())


def icon(
    name: str,
    color: str,
    size: int = 16,
    *,
    weight: float = DEFAULT_WEIGHT,
    disabled_color: str | None = None,
    active_color: str | None = None,
) -> QIcon:
    """A coloured icon; optional colours cover the disabled and hovered (active) modes."""
    result = QIcon()
    result.addPixmap(icon_pixmap(name, color, size, weight), QIcon.Mode.Normal)
    if disabled_color is not None:
        result.addPixmap(icon_pixmap(name, disabled_color, size, weight), QIcon.Mode.Disabled)
    if active_color is not None:
        result.addPixmap(icon_pixmap(name, active_color, size, weight), QIcon.Mode.Active)
    return result
