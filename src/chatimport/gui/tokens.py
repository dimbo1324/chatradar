"""Design tokens: the one file the whole window is built from.

No widget hard-codes a colour, a size or a duration. Pixel values here are the 100 % zoom
values; `ZoomManager.scaled` and the stylesheet builder multiply them. The structure mirrors
the codepack token set (a 4 px rhythm with two half-steps, a type scale, radii, motion,
layout sizes, two palettes) with an accent and a "live" teal tuned to the application icon.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

SPACE: Final[Mapping[int, int]] = {
    1: 2,
    2: 4,
    3: 6,
    4: 8,
    5: 12,
    6: 16,
    7: 20,
    8: 24,
    9: 32,
    10: 40,
    11: 56,
}

RADIUS: Final[Mapping[str, int]] = {"xs": 4, "sm": 6, "md": 8, "lg": 12, "xl": 16}

TEXT: Final[Mapping[str, int]] = {
    "2xs": 10,
    "xs": 11,
    "sm": 12,
    "base": 13,
    "md": 14,
    "lg": 16,
    "xl": 19,
    "2xl": 24,
    "3xl": 30,
}

WEIGHT: Final[Mapping[str, int]] = {"normal": 400, "medium": 500, "semibold": 600, "bold": 700}

DURATION: Final[Mapping[str, int]] = {"fast": 110, "base": 170, "slow": 260}

LAYOUT: Final[Mapping[str, int]] = {
    "sidebar": 232,
    "rail": 68,
    "content_max": 1080,
    "header": 52,
    "statusbar": 28,
    "control": 32,
    "control_sm": 26,
    "control_lg": 38,
    "nav_item": 34,
    "toast_width": 340,
    "icon_sm": 12,
    "icon_md": 16,
    "icon_lg": 20,
    "icon_xl": 40,
}

FONT_SANS: Final = ("Segoe UI Variable Text", "Segoe UI", "Cantarell", "Ubuntu", "Noto Sans")
FONT_DISPLAY: Final = ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI")
FONT_MONO: Final = (
    "Cascadia Mono",
    "Cascadia Code",
    "JetBrains Mono",
    "DejaVu Sans Mono",
    "Consolas",
)

ZOOM_MIN: Final = 0.7
ZOOM_MAX: Final = 2.0
ZOOM_STEP: Final = 0.05


@dataclass(frozen=True, slots=True)
class Palette:
    name: str

    canvas: str
    surface: str
    surface_raised: str
    surface_sunken: str
    surface_hover: str
    surface_active: str
    chrome: str

    fg: str
    fg_secondary: str
    fg_muted: str
    fg_faint: str
    fg_on_accent: str

    border: str
    border_strong: str
    border_focus: str

    accent: str
    accent_hover: str
    accent_active: str
    accent_soft: str
    accent_soft_border: str
    accent_fg: str

    live: str
    live_soft: str
    live_soft_border: str

    success: str
    success_soft: str
    success_soft_border: str

    warning: str
    warning_soft: str
    warning_soft_border: str

    danger: str
    danger_hover: str
    danger_soft: str
    danger_soft_border: str

    info: str
    info_soft: str
    info_soft_border: str

    focus_ring: str
    shadow: str
    scrollbar_thumb: str
    scrollbar_thumb_hover: str
    selection: str

    def colors(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "name"}


LIGHT: Final = Palette(
    name="light",
    canvas="#f3f6fa",
    surface="#ffffff",
    surface_raised="#ffffff",
    surface_sunken="#ecf0f6",
    surface_hover="#f0f4fa",
    surface_active="#e4eaf4",
    chrome="#fafcfe",
    fg="#121821",
    fg_secondary="#4a5566",
    fg_muted="#6b7788",
    fg_faint="#94a0b1",
    fg_on_accent="#ffffff",
    border="#e1e7ef",
    border_strong="#c8d1de",
    border_focus="#2f6bf0",
    accent="#2a62e6",
    accent_hover="#2250c4",
    accent_active="#1b409f",
    accent_soft="#e8f0ff",
    accent_soft_border="#bfd3fb",
    accent_fg="#1f4bb8",
    live="#0a9d8f",
    live_soft="#e0f6f3",
    live_soft_border="#b0e3dc",
    success="#10803f",
    success_soft="#e2f5e9",
    success_soft_border="#bde3cb",
    warning="#96610a",
    warning_soft="#fdf2dd",
    warning_soft_border="#eed7a6",
    danger="#c22a22",
    danger_hover="#a52019",
    danger_soft="#fdecea",
    danger_soft_border="#f3c8c4",
    info="#0a6c86",
    info_soft="#e2f4f9",
    info_soft_border="#b6dfeb",
    focus_ring="#a9c4fb",
    shadow="#101828",
    scrollbar_thumb="#c4ccd9",
    scrollbar_thumb_hover="#a8b2c2",
    selection="#dbe7ff",
)

DARK: Final = Palette(
    name="dark",
    canvas="#0b1017",
    surface="#131920",
    surface_raised="#18202a",
    surface_sunken="#0e141b",
    surface_hover="#1b2430",
    surface_active="#232e3c",
    chrome="#0f151c",
    fg="#e6ebf2",
    fg_secondary="#a7b2c2",
    fg_muted="#7f8b9d",
    fg_faint="#606b7b",
    fg_on_accent="#ffffff",
    border="#232c38",
    border_strong="#344050",
    border_focus="#6ea0ff",
    accent="#4a8bff",
    accent_hover="#6aa0ff",
    accent_active="#8bb6ff",
    accent_soft="#13234a",
    accent_soft_border="#27407a",
    accent_fg="#a9c8ff",
    live="#26d4c0",
    live_soft="#0c2a2b",
    live_soft_border="#17504f",
    success="#3fc477",
    success_soft="#10281b",
    success_soft_border="#1e4433",
    warning="#dfae4d",
    warning_soft="#2a2010",
    warning_soft_border="#4a3a1a",
    danger="#f87168",
    danger_hover="#ff8a82",
    danger_soft="#2c1517",
    danger_soft_border="#4d2528",
    info="#4cc0dd",
    info_soft="#0e2429",
    info_soft_border="#1c3e47",
    focus_ring="#2a4a8c",
    shadow="#000000",
    scrollbar_thumb="#323c4a",
    scrollbar_thumb_hover="#445064",
    selection="#1d3563",
)

PALETTES: Final[Mapping[str, Palette]] = {"light": LIGHT, "dark": DARK}
