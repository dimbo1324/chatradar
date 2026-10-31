"""Toasts: short notifications stacked in a window corner, auto-dismissed, paused on hover.

`ToastHost` is an overlay child of the main window (it follows the window's size); call it from
the main thread only. Cross-thread callers go through a queued signal (the notifier).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.i18n import tr
from chatimport.gui.icons import icon_pixmap
from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import DURATION, LAYOUT, SPACE
from chatimport.gui.widgets.base import TONE_ICONS, Tone, bind_kit
from chatimport.gui.widgets.button import IconButton

if TYPE_CHECKING:
    from PySide6.QtGui import QEnterEvent

    from chatimport.gui.kit import UiKit

MAX_VISIBLE: Final = 4
TIMEOUT_MS: Final[dict[str, int]] = {"danger": 12_000, "warning": 8_000}
DEFAULT_TIMEOUT_MS: Final = 5_000


class Toast(QFrame):
    def __init__(
        self,
        host: ToastHost,
        tone: Tone,
        message: str,
        title: str,
        timeout_ms: int,
    ) -> None:
        super().__init__(host)
        self.kit = host.kit
        self._host = host
        self._tone: Tone = tone
        self.setObjectName("Toast")
        self._icon = QLabel()
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title = QLabel(title)
        self._title.setObjectName("ToastTitle")
        self._title.setWordWrap(True)
        self._title.setVisible(bool(title))
        self._message = QLabel(message)
        self._message.setObjectName("ToastMessage")
        self._message.setWordWrap(True)
        self._message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._close = IconButton(self.kit, "x", tr("toast.dismiss"), size="sm")
        self._close.clicked.connect(self.dismiss)
        self._text = QVBoxLayout()
        self._text.setContentsMargins(0, 0, 0, 0)
        self._text.addWidget(self._title)
        self._text.addWidget(self._message)
        self._row = QHBoxLayout(self)
        self._row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        self._row.addLayout(self._text, 1)
        self._row.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(DURATION["base"])
        self._fade.valueChanged.connect(self._on_fade)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(self.dismiss)
        self._leaving = False
        self.setAccessibleName(f"{title} {message}".strip())
        bind_kit(self.kit, theme=self._restyle, zoom=self._restyle)
        self._restyle()
        self._fade_to(1.0)
        self._timer.start()

    def _restyle(self) -> None:
        px = self.kit.px
        self.setFixedWidth(px(LAYOUT["toast_width"]))
        self._row.setContentsMargins(px(SPACE[5]), px(SPACE[5]), px(SPACE[4]), px(SPACE[5]))
        self._row.setSpacing(px(SPACE[4]))
        self._text.setSpacing(px(SPACE[1]))
        color = tone_colors(self.kit.palette, self._tone)[2]
        if self._tone in ("neutral", "muted"):
            color = self.kit.palette.accent
        self._icon.setPixmap(icon_pixmap(TONE_ICONS[self._tone], color, px(LAYOUT["icon_lg"])))

    def _fade_to(self, target: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(target)
        self._fade.start()

    def _on_fade(self, value: object) -> None:
        opacity = float(value) if isinstance(value, float | int) else 1.0
        self._effect.setOpacity(opacity)
        if self._leaving and opacity <= 0.0:
            self._host.remove(self)

    def dismiss(self) -> None:
        if self._leaving:
            return
        self._leaving = True
        self._timer.stop()
        self._fade_to(0.0)

    def enterEvent(self, event: QEnterEvent) -> None:
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if not self._leaving:
            self._timer.start()
        super().leaveEvent(event)


class _ResizeWatcher(QObject):
    def __init__(self, host: ToastHost) -> None:
        super().__init__(host)
        self._host = host

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._host.follow_window()
        return False


class ToastHost(QWidget):
    def __init__(self, kit: UiKit, window: QWidget) -> None:
        super().__init__(window)
        self.kit = kit
        self._window = window
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._column = QVBoxLayout(self)
        self._column.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self._toasts: list[Toast] = []
        window.installEventFilter(_ResizeWatcher(self))
        bind_kit(kit, zoom=self._restyle)
        self._restyle()
        self.follow_window()
        self.show()

    def _restyle(self) -> None:
        px = self.kit.px
        gap = px(SPACE[6])
        self._column.setContentsMargins(gap, gap, gap, px(LAYOUT["statusbar"]) + gap)
        self._column.setSpacing(px(SPACE[4]))

    def follow_window(self) -> None:
        self.setGeometry(self._window.rect())
        self.raise_()

    def push(
        self, tone: Tone, message: str, *, title: str = "", timeout_ms: int | None = None
    ) -> Toast:
        limit = timeout_ms if timeout_ms is not None else TIMEOUT_MS.get(tone, DEFAULT_TIMEOUT_MS)
        toast = Toast(self, tone, message, title, limit)
        while len(self._toasts) >= MAX_VISIBLE:
            self.remove(self._toasts[0])
        self._toasts.append(toast)
        self._column.addWidget(toast, 0, Qt.AlignmentFlag.AlignRight)
        toast.show()
        self.raise_()
        return toast

    def push_key(self, tone: Tone, key: str, **params: object) -> Toast:
        """Translate `key` now (in the current language) and show it."""
        return self.push(tone, tr(key, **params))

    def remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            self._column.removeWidget(toast)
            toast.hide()
            toast.deleteLater()

    def clear(self) -> None:
        for toast in list(self._toasts):
            self.remove(toast)

    @property
    def count(self) -> int:
        return len(self._toasts)
