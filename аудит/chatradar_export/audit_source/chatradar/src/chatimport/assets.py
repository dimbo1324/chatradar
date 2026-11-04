"""Paths of the bundled artwork: the application icon as PNG (tray, README) and ICO (shortcuts,
future executable)."""

from __future__ import annotations

from pathlib import Path
from typing import Final

ASSETS_DIR: Final = Path(__file__).resolve().parent / "assets"
ICON_PNG: Final = ASSETS_DIR / "icon.png"
ICON_ICO: Final = ASSETS_DIR / "icon.ico"
