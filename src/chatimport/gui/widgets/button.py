"""Buttons: primary, secondary, ghost and danger variants, three sizes, optional stroke icon."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton

from chatimport.gui.icons import icon
from chatimport.gui.tokens import LAYOUT
from chatimport.gui.widgets.base import bind_kit, set_property

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit
    from chatimport.gui.tokens import Palette

type Variant = Literal["primary", "secondary", "ghost", "danger"]
type Size = Literal["sm", "md", "lg"]

_HEIGHT: Final[dict[str, str]] = {"sm": "control_sm", "md": "control", "lg": "control_lg"}
_ICON: Final[dict[str, str]] = {"sm": "icon_sm", "md": "icon_md", "lg": "icon_lg"}


def _icon_colors(palette: Palette, variant: Variant) -> tuple[str, str, str]:
    """(normal, hovered, disabled) icon colours for a variant."""
    if variant in ("primary", "danger"):
        return palette.fg_on_accent, palette.fg_on_accent, palette.fg_faint
    return palette.fg_secondary, palette.fg, palette.fg_faint


class Button(QPushButton):
    def __init__(
        self,
        kit: UiKit,
        text: str = "",
        *,
        variant: Variant = "secondary",
        size: Size = "md",
        icon_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.kit = kit
        self._variant: Variant = variant
        self._size: Size = size
        self._icon_name = icon_name
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("variant", variant)
        self.setProperty("size", size)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle)
        self._restyle()

    @property
    def variant(self) -> Variant:
        return self._variant

    def set_variant(self, variant: Variant) -> None:
        self._variant = variant
        set_property(self, "variant", variant)
        self._restyle()

    def set_icon_name(self, name: str | None) -> None:
        self._icon_name = name
        self._restyle()

    def _restyle(self) -> None:
        self.setFixedHeight(self.kit.px(LAYOUT[_HEIGHT[self._size]]))
        if self._icon_name is None:
            return
        size = self.kit.px(LAYOUT[_ICON[self._size]])
        normal, active, disabled = _icon_colors(self.kit.palette, self._variant)
        self.setIcon(
            icon(self._icon_name, normal, size, active_color=active, disabled_color=disabled)
        )
        self.setIconSize(QSize(size, size))


class IconButton(Button):
    """A square, icon-only button; `tooltip` doubles as the accessible name."""

    def __init__(
        self,
        kit: UiKit,
        icon_name: str,
        tooltip: str,
        *,
        variant: Variant = "ghost",
        size: Size = "md",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(kit, "", variant=variant, size=size, icon_name=icon_name, parent=parent)
        self.setProperty("iconOnly", True)
        self.set_tooltip(tooltip)

    def set_tooltip(self, text: str) -> None:
        self.setToolTip(text)
        self.setAccessibleName(text)

    def _restyle(self) -> None:
        super()._restyle()
        self.setFixedWidth(self.height())
