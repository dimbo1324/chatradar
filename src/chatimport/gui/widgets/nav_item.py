"""One sidebar row, painted by hand: icon, label, optional badge, active bar and focus ring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.tokens import LAYOUT, RADIUS, SPACE, TEXT, WEIGHT
from chatimport.gui.widgets.base import KEYBOARD_REASONS, bind_kit

if TYPE_CHECKING:
    from PySide6.QtGui import QEnterEvent, QFocusEvent, QKeyEvent, QPaintEvent
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.kit import UiKit
    from chatimport.gui.widgets.sidebar import Sidebar


class NavItem(QAbstractButton):
    def __init__(
        self,
        kit: UiKit,
        key: str,
        icon_name: str,
        label: str,
        *,
        selectable: bool = True,
        owner: Sidebar | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._keyboard_focus = False
        self.kit = kit
        self.key = key
        self._owner = owner
        self._icon_name = icon_name
        self._label = label
        self._badge = ""
        self._rail = False
        self._active = False
        self._hover = False
        self.setCheckable(False)
        self._selectable = selectable
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(label)
        bind_kit(kit, theme=self.update, zoom=self._resize)
        self._resize()

    def set_label(self, label: str) -> None:
        self._label = label
        self.setAccessibleName(label)
        self._sync_tooltip()
        self.update()

    def set_badge(self, text: str) -> None:
        self._badge = text
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def set_rail(self, rail: bool) -> None:
        self._rail = rail
        self._sync_tooltip()
        self.update()

    def _sync_tooltip(self) -> None:
        self.setToolTip(self._label if self._rail else "")

    def _resize(self) -> None:
        self.setFixedHeight(self.kit.px(LAYOUT["nav_item"]))
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(self.kit.px(LAYOUT["rail"]), self.kit.px(LAYOUT["nav_item"]))

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(Qt.Key(event.key()), 0)
        if step and self._owner is not None:
            self._owner.focus_neighbour(self, step)
            event.accept()
            return
        super().keyPressEvent(event)

    def _font(self, size_key: str, weight_key: str) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self.kit.px(TEXT[size_key]))
        font.setWeight(QFont.Weight(WEIGHT[weight_key]))
        return font

    def focusInEvent(self, event: QFocusEvent) -> None:
        self._keyboard_focus = event.reason() in KEYBOARD_REASONS
        super().focusInEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self.kit.palette
        px = self.kit.px
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(
            px(SPACE[1]), px(SPACE[1] / 2), -px(SPACE[1]), -px(SPACE[1] / 2)
        )
        radius = px(RADIUS["sm"])
        if self._active:
            painter.setBrush(QColor(palette.accent_soft))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, radius, radius)
            bar = QRectF(box.left(), box.top() + px(8), px(3), box.height() - px(16))
            painter.setBrush(QColor(palette.accent))
            painter.drawRoundedRect(bar, px(1.5), px(1.5))
        elif self._hover:
            painter.setBrush(QColor(palette.surface_hover))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(box, radius, radius)
        fg = (
            palette.accent_fg
            if self._active
            else (palette.fg if self._hover else palette.fg_secondary)
        )
        size = px(LAYOUT["icon_md"] + 2)
        pixmap = icon_pixmap(self._icon_name, fg, size)
        icon_x = (box.width() - size) / 2 + box.left() if self._rail else box.left() + px(SPACE[5])
        painter.drawPixmap(round(icon_x), round(box.center().y() - size / 2), pixmap)
        if self._rail:
            self._paint_focus(painter, box, radius)
            return
        text_left = icon_x + size + px(SPACE[4])
        right = box.right() - px(SPACE[4])
        if self._badge:
            right = self._paint_badge(painter, box, right) - px(SPACE[3])
        font = self._font("base", "medium")
        painter.setFont(font)
        painter.setPen(QColor(fg))
        metrics = QFontMetrics(font)
        text = metrics.elidedText(
            self._label, Qt.TextElideMode.ElideRight, max(round(right - text_left), 0)
        )
        text_box = QRectF(text_left, box.top(), max(right - text_left, 0), box.height())
        painter.drawText(
            text_box, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text
        )
        self._paint_focus(painter, box, radius)
        event.accept()

    def _paint_badge(self, painter: QPainter, box: QRectF, right: float) -> float:
        palette = self.kit.palette
        px = self.kit.px
        font = self._font("2xs", "semibold")
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(self._badge) + 2 * px(SPACE[3])
        height = metrics.height() + px(SPACE[1])
        pill = QRectF(right - width, box.center().y() - height / 2, width, height)
        painter.setBrush(QColor(palette.surface_sunken))
        painter.setPen(QPen(QColor(palette.border), 1))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setFont(font)
        painter.setPen(QColor(palette.fg_muted))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), self._badge)
        return pill.left()

    def _paint_focus(self, painter: QPainter, box: QRectF, radius: int) -> None:
        if not (self.hasFocus() and self._keyboard_focus):
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self.kit.palette.border_focus), max(self.kit.px(2), 2)))
        painter.drawRoundedRect(box.adjusted(1, 1, -1, -1), radius, radius)
