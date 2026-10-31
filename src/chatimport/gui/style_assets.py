"""Small SVG files the stylesheet points at (check mark, arrows): QSS can only reference files.

Written once per colour into the user's cache folder; the name carries the colour, so a theme
switch reuses what is already there and an older file is never rewritten.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from platformdirs import user_cache_dir

from chatimport.gui.icons import DEFAULT_WEIGHT, ICON_PATHS
from chatimport.paths import APP_NAME


def _folder() -> Path:
    return Path(user_cache_dir(APP_NAME)) / "gui-icons"


@lru_cache(maxsize=64)
def asset_url(name: str, color: str, weight: float = 2.2) -> str:
    """A `url(...)` token for QSS; falls back to `none` when the cache folder is not writable."""
    folder = _folder()
    target = folder / f"{name}-{color.lstrip('#')}.svg"
    if not target.exists():
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{weight or DEFAULT_WEIGHT}" stroke-linecap="round" '
            f'stroke-linejoin="round"><path d="{ICON_PATHS[name]}"/></svg>'
        )
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(svg, encoding="utf-8")
        except OSError:
            return "none"
    return f"url({target.as_posix()})"
