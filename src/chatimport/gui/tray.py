"""`QtTray`: the system tray icon with a state badge, a tooltip and a small menu.

The tray only emits requests; the window decides what they mean. Without a system tray the
object still exists (`available` is False) and every call is a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from chatimport.assets import ICON_PNG
from chatimport.gui.i18n import tr
from chatimport.runtime import Level

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit

type TrayState = Literal["running", "paused", "error"]

ICON_SIZE: Final = 64
BADGE_RADIUS: Final = 11
BADGE_RING: Final = 2.5
TOOLTIP_LIMIT: Final = 120
BADGE_COLORS: Final[dict[str, str]] = {
    "running": "#2ea043",
    "paused": "#808080",
    "error": "#c83030",
}
_LEVEL_ICONS: Final = {
    Level.INFO: QSystemTrayIcon.MessageIcon.Information,
    Level.WARNING: QSystemTrayIcon.MessageIcon.Warning,
    Level.ERROR: QSystemTrayIcon.MessageIcon.Critical,
}


def make_tray_icon(state: str) -> QIcon:
    """The application logo with a state badge: green running, grey paused, red failed."""
    logo = QPixmap(str(ICON_PNG)).scaled(
        ICON_SIZE,
        ICON_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(ICON_SIZE, ICON_SIZE)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, logo)
    center = QPointF(ICON_SIZE - 14, ICON_SIZE - 14)
    ring = BADGE_RADIUS + BADGE_RING
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawEllipse(QRectF(center.x() - ring, center.y() - ring, ring * 2, ring * 2))
    painter.setBrush(QBrush(QColor(BADGE_COLORS.get(state, BADGE_COLORS["paused"]))))
    painter.drawEllipse(
        QRectF(
            center.x() - BADGE_RADIUS,
            center.y() - BADGE_RADIUS,
            BADGE_RADIUS * 2,
            BADGE_RADIUS * 2,
        )
    )
    painter.end()
    return QIcon(canvas)


class QtTray(QObject):
    open_requested = Signal()
    toggle_pause_requested = Signal()
    recheck_requested = Signal()
    quit_requested = Signal()

    def __init__(self, kit: UiKit) -> None:
        super().__init__()
        self.kit = kit
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self._state: TrayState = "running"
        self._state_text = ""
        self._paused = False
        self._icon = QSystemTrayIcon(self)
        self._menu = QMenu()
        self._open = QAction(self)
        self._toggle = QAction(self)
        self._recheck = QAction(self)
        self._quit = QAction(self)
        self._open.triggered.connect(self.open_requested)
        self._toggle.triggered.connect(self.toggle_pause_requested)
        self._recheck.triggered.connect(self.recheck_requested)
        self._quit.triggered.connect(self.quit_requested)
        self._menu.addAction(self._open)
        self._menu.addSeparator()
        self._menu.addAction(self._toggle)
        self._menu.addAction(self._recheck)
        self._menu.addSeparator()
        self._menu.addAction(self._quit)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        kit.language.changed.connect(self._retranslate)
        self._retranslate()
        self._icon.setIcon(make_tray_icon(self._state))

    def show(self) -> None:
        if self.available:
            self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    @property
    def visible(self) -> bool:
        return self.available and self._icon.isVisible()

    def set_status(self, state: TrayState, state_text: str, *, paused: bool) -> None:
        if state != self._state:
            self._state = state
            self._icon.setIcon(make_tray_icon(state))
        self._state_text = state_text
        self._paused = paused
        self._retranslate()

    def show_message(self, level: Level, title: str, message: str) -> None:
        if self.available and self._icon.isVisible():
            self._icon.showMessage(title, message, _LEVEL_ICONS[level])

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_requested.emit()

    def _retranslate(self) -> None:
        self._open.setText(tr("shell.tray.open"))
        self._toggle.setText(tr("shell.tray.resume" if self._paused else "shell.tray.pause"))
        self._recheck.setText(tr("shell.tray.recheck"))
        self._quit.setText(tr("shell.tray.quit"))
        tip = tr("shell.tray.tip", state=self._state_text) if self._state_text else "ChatImport"
        self._icon.setToolTip(tip[:TOOLTIP_LIMIT])
