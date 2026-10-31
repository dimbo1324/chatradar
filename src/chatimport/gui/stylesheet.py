# ruff: noqa: E501 - QSS rules read best one per line
"""The QSS builder: one template, token placeholders, zoom-scaled pixel values.

`@name` placeholders resolve to a palette colour, a scaled pixel size (`@space_5`, `@text_base`,
`@radius_md`, `@layout_control`), a font stack or a weight. Borders stay 1 px at every zoom.
A focus ring is a 2 px border with the padding reduced by 1 px, so focus never moves the text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from chatimport.gui.style_assets import asset_url
from chatimport.gui.tokens import (
    FONT_DISPLAY,
    FONT_MONO,
    FONT_SANS,
    LAYOUT,
    RADIUS,
    SPACE,
    TEXT,
    WEIGHT,
)

if TYPE_CHECKING:
    from chatimport.gui.tokens import Palette

TONES: Final = ("neutral", "accent", "live", "success", "warning", "danger", "info", "muted")

_PLACEHOLDER: Final = re.compile(r"@([a-z0-9_]+)")

_BASE: Final = """
* { outline: 0; }
QWidget { color: @fg; font-family: @font_sans; font-size: @text_base; }
QMainWindow, QDialog, QMessageBox { background: @canvas; }
QLabel { background: transparent; }
QLabel:disabled { color: @fg_faint; }
QLabel[role="muted"] { color: @fg_muted; }
QLabel[role="secondary"] { color: @fg_secondary; }
QLabel[role="faint"] { color: @fg_faint; }
QLabel[role="sm"] { font-size: @text_sm; }
QLabel[role="caption"] { color: @fg_muted; font-size: @text_xs; }
QLabel[role="eyebrow"] { color: @fg_faint; font-size: @text_2xs; font-weight: @weight_semibold; }
QLabel[role="section"] { font-family: @font_display; font-size: @text_md; font-weight: @weight_semibold; }
QLabel[role="title"] { font-family: @font_display; font-size: @text_xl; font-weight: @weight_semibold; }
QLabel[role="display"] { font-family: @font_display; font-size: @text_2xl; font-weight: @weight_semibold; }
QLabel[role="mono"] { font-family: @font_mono; font-size: @text_sm; color: @fg_secondary; }
QLabel[role="link"] { color: @accent; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QFrame[role="divider"] { background: @border; border: none; max-height: 1px; min-height: 1px; }
QFrame[role="vdivider"] { background: @border; border: none; max-width: 1px; min-width: 1px; }
QToolTip {
    background: @surface_raised; color: @fg; border: 1px solid @border_strong;
    padding: @space_3 @space_4; font-size: @text_sm;
}

QFrame[role="card"] {
    background: @surface; border: 1px solid @border; border-radius: @radius_lg;
}
QFrame[role="card"][flat="true"] { background: transparent; }
QFrame[role="surface-sunken"] {
    background: @surface_sunken; border: 1px solid @border; border-radius: @radius_md;
}

QPushButton {
    background: @surface; color: @fg; border: 1px solid @border_strong;
    border-radius: @radius_sm; padding: 0 @space_5; font-weight: @weight_medium;
}
QPushButton:hover { background: @surface_hover; border-color: @fg_faint; }
QPushButton:pressed { background: @surface_active; }
QPushButton:focus { border: 2px solid @border_focus; padding: 0 @space_5_less; }
QPushButton:disabled { background: @surface_sunken; color: @fg_faint; border-color: @border; }
QPushButton[variant="primary"] { background: @accent; color: @fg_on_accent; border-color: @accent; }
QPushButton[variant="primary"]:hover { background: @accent_hover; border-color: @accent_hover; }
QPushButton[variant="primary"]:pressed { background: @accent_active; border-color: @accent_active; }
QPushButton[variant="primary"]:focus { border: 2px solid @border_focus; }
QPushButton[variant="primary"]:disabled { background: @accent_soft; color: @fg_faint; border-color: @accent_soft_border; }
QPushButton[variant="danger"] { background: @danger; color: #ffffff; border-color: @danger; }
QPushButton[variant="danger"]:hover { background: @danger_hover; border-color: @danger_hover; }
QPushButton[variant="danger"]:focus { border: 2px solid @border_focus; }
QPushButton[variant="danger"]:disabled { background: @danger_soft; color: @fg_faint; border-color: @danger_soft_border; }
QPushButton[variant="ghost"] { background: transparent; color: @fg_secondary; border-color: transparent; }
QPushButton[variant="ghost"]:hover { background: @surface_hover; color: @fg; border-color: transparent; }
QPushButton[variant="ghost"]:pressed { background: @surface_active; }
QPushButton[variant="ghost"]:focus { border: 2px solid @border_focus; }
QPushButton[variant="ghost"]:disabled { background: transparent; color: @fg_faint; border-color: transparent; }
QPushButton[iconOnly="true"] { padding: 0; }
QPushButton[iconOnly="true"]:focus { padding: 0; }
QPushButton[size="sm"] { font-size: @text_sm; padding: 0 @space_4; }
QPushButton[size="sm"]:focus { padding: 0 @space_4_less; }
QPushButton[size="lg"] { font-size: @text_md; padding: 0 @space_7; }
QPushButton[size="lg"]:focus { padding: 0 @space_7_less; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {
    background: @surface; color: @fg; border: 1px solid @border_strong; border-radius: @radius_sm;
    padding: 0 @space_4; selection-background-color: @selection; selection-color: @fg;
}
QPlainTextEdit, QTextEdit { padding: @space_3 @space_4; }
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover { border-color: @fg_faint; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid @border_focus; padding: 0 @space_4_less;
}
QPlainTextEdit:focus, QTextEdit:focus { padding: @space_3_less @space_4_less; }
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
    background: @surface_sunken; color: @fg_faint; border-color: @border;
}
QLineEdit[role="mono"] { font-family: @font_mono; font-size: @text_sm; }

QComboBox {
    background: @surface; color: @fg; border: 1px solid @border_strong; border-radius: @radius_sm;
    padding: 0 @space_4; min-height: @control_inner;
}
QComboBox:hover { border-color: @fg_faint; }
QComboBox:focus { border: 2px solid @border_focus; padding: 0 @space_4_less; }
QComboBox:disabled { background: @surface_sunken; color: @fg_faint; border-color: @border; }
QComboBox::drop-down { border: none; width: @space_8; }
QComboBox::down-arrow { image: @arrow_down; width: @icon_sm; height: @icon_sm; }
QComboBox QAbstractItemView {
    background: @surface_raised; border: 1px solid @border_strong; padding: @space_2;
    selection-background-color: @accent_soft; selection-color: @accent_fg;
}

QCheckBox, QRadioButton { spacing: @space_4; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator {
    width: @icon_md; height: @icon_md; border: 1px solid @border_strong; background: @surface;
}
QCheckBox::indicator { border-radius: @radius_xs; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: @check_on_accent; }
QRadioButton::indicator:checked { background: @accent; border: 4px solid @surface; }
QCheckBox:focus, QRadioButton:focus { color: @fg; }
QCheckBox::indicator:focus { border: 2px solid @border_focus; }

QScrollBar:vertical { background: transparent; width: @scroll; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: @scroll; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: @scrollbar_thumb; border-radius: @scroll_radius; min-height: 28px; min-width: 28px;
}
QScrollBar::handle:hover { background: @scrollbar_thumb_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QMenu {
    background: @surface_raised; border: 1px solid @border_strong; padding: @space_2;
}
QMenu::item { padding: @space_3 @space_9 @space_3 @space_5; border-radius: @radius_xs; color: @fg; }
QMenu::item:selected { background: @surface_hover; }
QMenu::item:disabled { color: @fg_faint; }
QMenu::separator { height: 1px; background: @border; margin: @space_2 @space_3; }
QMenu::icon { padding-left: @space_3; }

QTableView, QTreeView, QListView {
    background: @surface; alternate-background-color: @surface; color: @fg;
    border: 1px solid @border; border-radius: @radius_lg;
    selection-background-color: @selection; selection-color: @fg; gridline-color: transparent;
}
QTableView::item, QTreeView::item { padding: 0 @space_4; border: none; }
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover { background: @surface_hover; }
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
    background: @selection; color: @fg;
}
QHeaderView { background: @surface_sunken; border: none; }
QHeaderView::section {
    background: @surface_sunken; color: @fg_muted; border: none;
    border-bottom: 1px solid @border; padding: @space_3 @space_5;
    font-size: @text_xs; font-weight: @weight_semibold;
}
QHeaderView::section:hover { color: @fg; }
QHeaderView::up-arrow { image: @arrow_up; width: @icon_sm; height: @icon_sm; }
QHeaderView::down-arrow { image: @arrow_down; width: @icon_sm; height: @icon_sm; }
QTableCornerButton::section { background: @surface_sunken; border: none; }

QProgressBar {
    background: @surface_active; border: none; border-radius: @space_2; max-height: @space_3;
    text-align: center; color: transparent;
}
QProgressBar::chunk { background: @accent; border-radius: @space_2; }
QSplitter::handle { background: @border; }
QSlider::groove:horizontal { height: @space_2; background: @surface_active; border-radius: @space_1; }
QSlider::handle:horizontal {
    background: @accent; width: @icon_md; margin: -@space_3 0; border-radius: @radius_md;
}
QTabBar::tab {
    padding: @space_3 @space_6; color: @fg_secondary; border-bottom: 2px solid transparent;
}
QTabBar::tab:selected { color: @accent_fg; border-bottom-color: @accent; }
QTabBar::tab:hover { color: @fg; }

QMessageBox QLabel { color: @fg; }
QDialogButtonBox QPushButton { min-width: @button_min; min-height: @control_inner; }
QMessageBox QPushButton { min-width: @button_min; min-height: @control_inner; }

QFrame#Sidebar { background: @chrome; border: none; border-right: 1px solid @border; }
QFrame#TopBar { background: @chrome; border: none; border-bottom: 1px solid @border; }
QFrame#StatusBar { background: @chrome; border: none; border-top: 1px solid @border; }
QFrame#StatusBar QLabel { color: @fg_muted; font-size: @text_xs; }
QLabel#TopBarTitle { font-family: @font_display; font-size: @text_lg; font-weight: @weight_semibold; }
QLabel#TopBarSubtitle { color: @fg_muted; font-size: @text_sm; }
QLabel#BrandName { font-family: @font_display; font-size: @text_md; font-weight: @weight_semibold; }
QLabel#BrandTagline { color: @fg_muted; font-size: @text_2xs; }
QLabel#NavHeading { color: @fg_faint; font-size: @text_2xs; font-weight: @weight_semibold; }
QPushButton#ZoomButton {
    background: transparent; border: 1px solid transparent; border-radius: @radius_xs;
    color: @fg_muted; padding: 0 @space_2; font-size: @text_xs; font-weight: @weight_normal;
}
QPushButton#ZoomButton:hover { background: @surface_hover; border-color: @border; color: @fg; }
QPushButton#ZoomButton:focus { border: 1px solid @border_focus; padding: 0 @space_2; }
QPushButton#ZoomButton:disabled { background: transparent; color: @fg_faint; border-color: transparent; }

QFrame#SegmentedTrack {
    background: @surface_sunken; border: 1px solid @border; border-radius: @radius_md;
}
QPushButton#SegmentedOption {
    background: transparent; border: 1px solid transparent; border-radius: @radius_sm;
    color: @fg_secondary; padding: 0 @space_5; font-weight: @weight_medium;
}
QPushButton#SegmentedOption:hover { background: @surface_hover; color: @fg; border-color: transparent; }
QPushButton#SegmentedOption:checked { background: @surface; color: @fg; border-color: @border; }
QPushButton#SegmentedOption:focus { border: 2px solid @border_focus; padding: 0 @space_5_less; }
QPushButton#SegmentedOption[unavailable="true"] { color: @fg_faint; }
QPushButton#SegmentedOption[compact="true"] { padding: 0 @space_4; }
QPushButton#SegmentedOption[compact="true"]:focus { padding: 0 @space_4_less; }
QLabel#SegmentedNote { color: @fg_muted; font-size: @text_sm; }

QFrame#Chip { border-radius: @radius_xl; }
QFrame#Chip QLabel { font-size: @text_xs; font-weight: @weight_medium; }
QFrame#EmptyState { background: transparent; border: none; }
QLabel#EmptyTitle { font-family: @font_display; font-size: @text_md; font-weight: @weight_semibold; }
QLabel#EmptyText { color: @fg_muted; }

QFrame#StatCard { border-radius: @radius_md; }
QLabel#StatLabel { font-size: @text_sm; font-weight: @weight_medium; color: @fg_muted; }
QLabel#StatValue { font-family: @font_display; font-size: @text_2xl; font-weight: @weight_semibold; }
QLabel#StatHint { color: @fg_muted; font-size: @text_xs; }

QLabel#CalloutTitle { font-weight: @weight_semibold; }
QLabel#CalloutBody { color: @fg; }

QFrame#Toast { background: @surface_raised; border: 1px solid @border_strong; border-radius: @radius_md; }
QLabel#ToastTitle { font-weight: @weight_semibold; }
QLabel#ToastMessage { color: @fg_secondary; }

QMessageBox QLabel#qt_msgbox_label { min-width: 240px; }
"""

_TONE_BLOCK: Final = """
QFrame#Callout[tone="@tone"] { background: @tone_bg; border: 1px solid @tone_border; border-radius: @radius_md; }
QLabel#CalloutIcon[tone="@tone"] { color: @tone_fg; }
QFrame#StatCard[tone="@tone"] { background: @stat_bg; border: 1px solid @stat_border; }
QFrame#StatCard[tone="@tone"] QLabel#StatValue { color: @stat_fg; }
QFrame#StatCard[tone="@tone"] QLabel#StatLabel { color: @stat_label; }
QFrame#Chip[tone="@tone"] { background: @tone_bg; border: 1px solid @tone_border; }
QFrame#Chip[tone="@tone"] QLabel { color: @tone_fg; }
"""


def tone_colors(palette: Palette, tone: str) -> tuple[str, str, str]:
    """(background, border, foreground) for a tone name."""
    table = {
        "neutral": (palette.surface_sunken, palette.border, palette.fg_secondary),
        "muted": (palette.surface_sunken, palette.border, palette.fg_muted),
        "accent": (palette.accent_soft, palette.accent_soft_border, palette.accent_fg),
        "live": (palette.live_soft, palette.live_soft_border, palette.live),
        "success": (palette.success_soft, palette.success_soft_border, palette.success),
        "warning": (palette.warning_soft, palette.warning_soft_border, palette.warning),
        "danger": (palette.danger_soft, palette.danger_soft_border, palette.danger),
        "info": (palette.info_soft, palette.info_soft_border, palette.info),
    }
    return table[tone]


def _px(value: float, scale: float) -> str:
    return f"{max(round(value * scale), 1)}px"


def _family(names: tuple[str, ...], generic: str) -> str:
    return ", ".join([*(f'"{name}"' for name in names), generic])


def _mapping(palette: Palette, scale: float) -> dict[str, str]:
    values: dict[str, str] = dict(palette.colors())
    for index, size in SPACE.items():
        values[f"space_{index}"] = _px(size, scale)
        values[f"space_{index}_less"] = _px(size - 1, scale)
    values["space_3_less"] = _px(SPACE[3] - 1, scale)
    values.update({f"radius_{name}": _px(size, scale) for name, size in RADIUS.items()})
    values.update({f"text_{name}": _px(size, scale) for name, size in TEXT.items()})
    values.update({f"layout_{name}": _px(size, scale) for name, size in LAYOUT.items()})
    values.update({f"weight_{name}": str(weight) for name, weight in WEIGHT.items()})
    values["icon_sm"] = _px(LAYOUT["icon_sm"], scale)
    values["icon_md"] = _px(LAYOUT["icon_md"], scale)
    values["control_inner"] = _px(LAYOUT["control"] - 2, scale)
    values["button_min"] = _px(72, scale)
    values["scroll"] = _px(10, scale)
    values["scroll_radius"] = _px(3, scale)
    values["font_sans"] = _family(FONT_SANS, "sans-serif")
    values["font_display"] = _family(FONT_DISPLAY, "sans-serif")
    values["font_mono"] = _family(FONT_MONO, "monospace")
    values["arrow_down"] = asset_url("chevron-down", palette.fg_muted)
    values["arrow_up"] = asset_url("chevron-up", palette.fg_muted)
    values["check_on_accent"] = asset_url("check", palette.fg_on_accent)
    return values


def _resolve(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def build_stylesheet(palette: Palette, scale: float = 1.0) -> str:
    """The whole application stylesheet for `palette` at zoom `scale`."""
    values = _mapping(palette, scale)
    parts = [_resolve(_BASE, values)]
    for tone in TONES:
        bg, border, fg = tone_colors(palette, tone)
        stat = tone == "neutral"
        tone_values = {
            **values,
            "tone": tone,
            "tone_bg": bg,
            "tone_border": border,
            "tone_fg": fg,
            "stat_bg": palette.surface if stat else bg,
            "stat_border": palette.border if stat else border,
            "stat_fg": palette.fg if stat else fg,
            "stat_label": palette.fg_muted if stat else fg,
        }
        parts.append(_resolve(_TONE_BLOCK, tone_values))
    return "\n".join(parts)
