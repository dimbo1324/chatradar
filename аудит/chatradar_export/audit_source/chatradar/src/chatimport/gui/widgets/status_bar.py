"""The status bar: the permanent "everything stays on this computer" statement, zoom, version."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.icons import icon, icon_pixmap
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.labels import ElidedLabel

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit

_ICON_SIZE = 12


class _ZoomButton(QPushButton):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setObjectName("ZoomButton")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class StatusBar(QFrame):
    def __init__(self, kit: UiKit, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        self.setObjectName("StatusBar")
        self._version = version
        self._lock = QLabel()
        self._privacy = ElidedLabel()
        self._extras = QHBoxLayout()
        self._zoom_out = _ZoomButton()
        self._zoom_value = _ZoomButton()
        self._zoom_in = _ZoomButton()
        self._version_label = QLabel()
        self._row = QHBoxLayout(self)
        self._row.addWidget(self._lock)
        self._row.addWidget(self._privacy, 1)
        self._row.addLayout(self._extras)
        for part in (self._zoom_out, self._zoom_value, self._zoom_in, self._version_label):
            self._row.addWidget(part)
        self._zoom_out.clicked.connect(kit.zoom.zoom_out)
        self._zoom_in.clicked.connect(kit.zoom.zoom_in)
        self._zoom_value.clicked.connect(kit.zoom.reset)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()

    def add_item(self, widget: QWidget) -> None:
        """Dynamic items (service state, disk) go between the statement and the zoom."""
        self._extras.addWidget(widget)

    def _retranslate(self) -> None:
        self._privacy.setText(tr("status.local"))
        self._privacy.setToolTip(tr("status.local_tip"))
        self._lock.setToolTip(tr("status.local_tip"))
        self._version_label.setText(tr("status.version", version=self._version))
        self._zoom_out.setToolTip(tr("status.zoom.out"))
        self._zoom_out.setAccessibleName(tr("status.zoom.out"))
        self._zoom_in.setToolTip(tr("status.zoom.in"))
        self._zoom_in.setAccessibleName(tr("status.zoom.in"))
        self._sync_zoom()

    def _sync_zoom(self) -> None:
        zoom = self.kit.zoom
        mark = f" {tr('status.zoom.auto_mark')}" if zoom.auto else ""
        self._zoom_value.setText(f"{zoom.percent}%{mark}")
        tip = tr("status.zoom.auto") if zoom.auto else tr("status.zoom.reset")
        self._zoom_value.setToolTip(tip)
        self._zoom_value.setAccessibleName(f"{tr('status.zoom.label')} {zoom.percent}%")
        self._zoom_out.setEnabled(zoom.can_zoom_out)
        self._zoom_in.setEnabled(zoom.can_zoom_in)

    def _restyle(self) -> None:
        px = self.kit.px
        palette = self.kit.palette
        self.setFixedHeight(px(LAYOUT["statusbar"]))
        self._row.setContentsMargins(px(SPACE[6]), 0, px(SPACE[6]), 0)
        self._row.setSpacing(px(SPACE[4]))
        self._extras.setSpacing(px(SPACE[6]))
        size = px(_ICON_SIZE)
        self._lock.setPixmap(icon_pixmap("lock", palette.live, size))
        side = px(18)
        for button in (self._zoom_out, self._zoom_in):
            button.setFixedSize(side, side)
        button_icons = ((self._zoom_out, "minus"), (self._zoom_in, "plus"))
        for button, name in button_icons:
            button.setIcon(
                icon(
                    name,
                    palette.fg_muted,
                    size,
                    active_color=palette.fg,
                    disabled_color=palette.fg_faint,
                )
            )
            button.setIconSize(QSize(size, size))
        self._zoom_value.setFixedHeight(side)
        self._zoom_value.setMinimumWidth(px(44))
        self._sync_zoom()
