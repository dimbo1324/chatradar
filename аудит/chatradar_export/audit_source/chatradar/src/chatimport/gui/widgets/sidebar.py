"""The collapsible sidebar: brand, sectioned navigation, collapse toggle (full width or icon rail).

Entries carry translation keys, so a language change relabels everything. An entry may show a
badge ("Soon") and may be locked: clicking a locked entry emits `locked` with the reason
instead of navigating, so a locked item explains itself rather than doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from chatimport.assets import ICON_PNG
from chatimport.gui.i18n import tr
from chatimport.gui.tokens import DURATION, LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.nav_item import NavItem

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chatimport.gui.kit import UiKit

COLLAPSE_KEY = "__collapse__"
LOGO_SIZE = 28


@dataclass(frozen=True, slots=True)
class NavEntry:
    key: str
    label_key: str
    icon: str
    badge_key: str | None = None
    locked_key: str | None = None


@dataclass(frozen=True, slots=True)
class NavSection:
    label_key: str
    entries: tuple[NavEntry, ...]


class Sidebar(QFrame):
    navigate = Signal(str)
    locked = Signal(str, str)
    collapsed_changed = Signal(bool)

    def __init__(
        self,
        kit: UiKit,
        sections: Sequence[NavSection],
        *,
        current: str | None = None,
        collapsed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("Sidebar")
        self._sections = list(sections)
        self._collapsed = collapsed
        self._current = current
        self._items: dict[str, NavItem] = {}
        self._entries: dict[str, NavEntry] = {}
        self._headings: list[tuple[str, QLabel]] = []
        self._badges: dict[str, str] = {}
        self._build()
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(DURATION["base"])
        self._anim.valueChanged.connect(self._on_width)
        self._anim.finished.connect(self._after_animation)
        bind_kit(kit, theme=self._restyle, zoom=self._on_zoom, language=self._retranslate)
        self._retranslate()
        self._restyle()
        self._apply_collapsed()
        self.set_current(current)
        self.setFixedWidth(self._target_width())

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    @property
    def current(self) -> str | None:
        return self._current

    def _build(self) -> None:
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)
        self._brand = QWidget()
        self._brand_row = QHBoxLayout(self._brand)
        self._logo = QLabel()
        self._logo.setAccessibleName(tr("app.title"))
        self._brand_texts = QWidget()
        texts = QVBoxLayout(self._brand_texts)
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        self._name = QLabel()
        self._name.setObjectName("BrandName")
        self._tagline = QLabel()
        self._tagline.setObjectName("BrandTagline")
        texts.addWidget(self._name)
        texts.addWidget(self._tagline)
        self._brand_row.addWidget(self._logo)
        self._brand_row.addWidget(self._brand_texts, 1)
        self._column.addWidget(self._brand)
        self._nav = QVBoxLayout()
        self._nav.setSpacing(0)
        for section in self._sections:
            heading = QLabel()
            heading.setObjectName("NavHeading")
            self._headings.append((section.label_key, heading))
            self._nav.addWidget(heading)
            for entry in section.entries:
                item = NavItem(self.kit, entry.key, entry.icon, "", owner=self)
                item.clicked.connect(lambda _=False, key=entry.key: self._activate(key))
                self._items[entry.key] = item
                self._entries[entry.key] = entry
                self._nav.addWidget(item)
        self._column.addLayout(self._nav)
        self._column.addStretch(1)
        self._toggle = NavItem(self.kit, COLLAPSE_KEY, "panel-left", "", owner=self)
        self._toggle.clicked.connect(self.toggle)
        self._bottom = QVBoxLayout()
        self._bottom.addWidget(self._toggle)
        self._column.addLayout(self._bottom)

    def focus_neighbour(self, item: NavItem, step: int) -> None:
        order = [*self._items.values(), self._toggle]
        target = order[(order.index(item) + step) % len(order)]
        target.setFocus(Qt.FocusReason.TabFocusReason)

    def _activate(self, key: str) -> None:
        entry = self._entries[key]
        if entry.locked_key:
            self.locked.emit(key, tr(entry.locked_key))
            return
        self.set_current(key)
        self.navigate.emit(key)

    def set_current(self, key: str | None) -> None:
        self._current = key
        for item_key, item in self._items.items():
            item.set_active(item_key == key)

    def set_badge(self, key: str, text: str | None) -> None:
        """Override an entry's badge (for example a count); `None` restores the default."""
        if text is None:
            self._badges.pop(key, None)
        else:
            self._badges[key] = text
        self._retranslate()

    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, *, animate: bool = True) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._retranslate()
        if collapsed:
            self._hide_texts(True)
        else:
            self._apply_collapsed()
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self.width())
            self._anim.setEndValue(self._target_width())
            self._anim.start()
        else:
            self.setFixedWidth(self._target_width())
            self._apply_collapsed()
        self.collapsed_changed.emit(collapsed)

    def _target_width(self) -> int:
        return self.kit.px(LAYOUT["rail"] if self._collapsed else LAYOUT["sidebar"])

    def _on_width(self, value: object) -> None:
        if isinstance(value, int | float):
            self.setFixedWidth(round(value))

    def _after_animation(self) -> None:
        self.setFixedWidth(self._target_width())
        self._apply_collapsed()

    def _hide_texts(self, hidden: bool) -> None:
        self._brand_texts.setVisible(not hidden)
        for _key, heading in self._headings:
            heading.setVisible(not hidden)

    def _apply_collapsed(self) -> None:
        self._hide_texts(self._collapsed)
        for item in (*self._items.values(), self._toggle):
            item.set_rail(self._collapsed)
        self._restyle()

    def _on_zoom(self) -> None:
        self.setFixedWidth(self._target_width())
        self._restyle()

    def _retranslate(self) -> None:
        self._name.setText(tr("app.title"))
        self._tagline.setText(tr("app.tagline"))
        self._logo.setAccessibleName(tr("app.title"))
        for label_key, heading in self._headings:
            heading.setText(tr(label_key).upper())
        for key, item in self._items.items():
            entry = self._entries[key]
            item.set_label(tr(entry.label_key))
            badge = self._badges.get(key) or (tr(entry.badge_key) if entry.badge_key else "")
            item.set_badge(badge)
        toggle_text = tr("nav.expand" if self._collapsed else "nav.collapse")
        self._toggle.set_label(toggle_text)
        self._toggle.setToolTip(toggle_text)
        self.setAccessibleName(tr("nav.label"))

    def _restyle(self) -> None:
        px = self.kit.px
        pad = px(SPACE[4])
        self._brand.setFixedHeight(px(LAYOUT["header"]))
        self._brand_row.setContentsMargins(px(SPACE[5]) if not self._collapsed else 0, 0, pad, 0)
        self._brand_row.setSpacing(px(SPACE[4]))
        self._brand_row.setAlignment(
            Qt.AlignmentFlag.AlignCenter if self._collapsed else Qt.AlignmentFlag.AlignVCenter
        )
        self._nav.setContentsMargins(pad, px(SPACE[2]), pad, 0)
        self._bottom.setContentsMargins(pad, 0, pad, 0)
        self._column.setContentsMargins(0, 0, 0, px(SPACE[4]))
        for _key, heading in self._headings:
            heading.setContentsMargins(px(SPACE[4]), px(SPACE[5]), 0, px(SPACE[2]))
        logo_size = px(LOGO_SIZE)
        dpr = self.devicePixelRatioF() or 1.0
        pixmap = QPixmap(str(ICON_PNG)).scaled(
            round(logo_size * dpr),
            round(logo_size * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap.setDevicePixelRatio(dpr)
        self._logo.setPixmap(pixmap)
        self._logo.setFixedSize(logo_size, logo_size)
