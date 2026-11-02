"""Small painted schemes for the API key guide: simplified sketches, not screenshots.

Every scheme is drawn in a fixed 240 x 96 box and scaled to the widget, so the sketches follow
the theme colours and the zoom. The words in them copy what my.telegram.org shows (it is
English only), so they are not translated.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.widgets.base import bind_kit

if TYPE_CHECKING:
    from PySide6.QtGui import QPaintEvent

    from chatimport.gui.kit import UiKit
    from chatimport.gui.tokens import Palette

BOX_WIDTH: Final = 240
BOX_HEIGHT: Final = 96
KINDS: Final = ("site", "phone", "code", "tools", "form", "create", "keys")
FORM_FIELDS: Final = (
    ("App title", "My archive"),
    ("Short name", "myarchive1"),
    ("Platform", "Desktop"),
)


def _text(painter: QPainter, rect: QRectF, text: str, color: str, *, bold: bool = False) -> None:
    font = QFont(painter.font())
    font.setPixelSize(11)
    font.setBold(bold)
    painter.setFont(font)
    painter.setPen(QColor(color))
    flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    painter.drawText(rect, flags, text)


def _box(
    painter: QPainter,
    rect: QRectF,
    fill: str,
    border: str,
    radius: float = 5,
    width: float = 1,
) -> None:
    painter.setBrush(QColor(fill))
    pen = QPen(QColor(border))
    pen.setWidthF(width)
    painter.setPen(pen)
    painter.drawRoundedRect(rect, radius, radius)


def _field(
    painter: QPainter, palette: Palette, rect: QRectF, text: str, *, active: bool = False
) -> None:
    _box(
        painter,
        rect,
        palette.surface,
        palette.accent if active else palette.border_strong,
        4,
        1.6 if active else 1,
    )
    _text(painter, rect.adjusted(7, 0, -4, 0), text, palette.fg if text else palette.fg_faint)


def _button(painter: QPainter, palette: Palette, rect: QRectF, text: str) -> None:
    _box(painter, rect, palette.accent, palette.accent, 5)
    painter.setPen(QColor(palette.fg_on_accent))
    font = QFont(painter.font())
    font.setPixelSize(11)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


def _site(painter: QPainter, palette: Palette) -> None:
    _box(painter, QRectF(14, 12, 212, 72), palette.surface, palette.border_strong, 6)
    painter.setPen(Qt.PenStyle.NoPen)
    for index, color in enumerate((palette.danger, palette.warning, palette.success)):
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(26 + index * 11, 24), 3, 3)
    _box(painter, QRectF(70, 17, 148, 14), palette.surface_sunken, palette.border, 7)
    painter.drawPixmap(QPointF(76, 19), icon_pixmap("lock", palette.success, 10))
    _text(painter, QRectF(90, 17, 126, 14), "my.telegram.org", palette.fg)
    _box(painter, QRectF(28, 44, 100, 8), palette.surface_sunken, palette.surface_sunken, 3)
    _box(painter, QRectF(28, 58, 160, 8), palette.surface_sunken, palette.surface_sunken, 3)


def _phone(painter: QPainter, palette: Palette) -> None:
    _text(painter, QRectF(30, 8, 180, 16), "Your Phone Number", palette.fg_muted)
    _field(painter, palette, QRectF(30, 28, 180, 24), "+598 99 123 456", active=True)
    _button(painter, palette, QRectF(30, 62, 82, 22), "Next")


def _code(painter: QPainter, palette: Palette) -> None:
    painter.drawPixmap(QPointF(24, 36), icon_pixmap("send", palette.accent, 22))
    _box(painter, QRectF(54, 22, 160, 44), palette.accent_soft, palette.accent_soft_border, 8)
    _text(painter, QRectF(62, 24, 148, 18), "Login code: 48213", palette.accent_fg, bold=True)
    _text(painter, QRectF(62, 42, 148, 18), "Telegram", palette.fg_muted)


def _tools(painter: QPainter, palette: Palette) -> None:
    items = ("Log out", "API development tools", "Delete account")
    for index, label in enumerate(items):
        row = QRectF(30, 10 + index * 25, 180, 22)
        chosen = index == 1
        fill = palette.accent_soft if chosen else palette.surface
        edge = palette.accent if chosen else palette.border
        _box(painter, row, fill, edge, 5, 1.6 if chosen else 1)
        _text(
            painter, row.adjusted(8, 0, -4, 0), label, palette.accent_fg if chosen else palette.fg
        )


def _form(painter: QPainter, palette: Palette) -> None:
    for index, (label, value) in enumerate(FORM_FIELDS):
        top = 8 + index * 28
        _text(painter, QRectF(14, top, 70, 22), label, palette.fg_muted)
        _field(painter, palette, QRectF(88, top, 138, 22), value, active=index == 1)


def _create(painter: QPainter, palette: Palette) -> None:
    _button(painter, palette, QRectF(40, 28, 160, 34), "Create application")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette.accent))
    painter.drawEllipse(QPointF(184, 58), 7, 7)
    painter.drawPixmap(QPointF(177, 51), icon_pixmap("check", palette.fg_on_accent, 14))


def _keys(painter: QPainter, palette: Palette) -> None:
    _text(painter, QRectF(14, 8, 70, 20), "App api_id", palette.fg_muted)
    _field(painter, palette, QRectF(90, 8, 136, 22), "12345678")
    _text(painter, QRectF(14, 36, 70, 20), "App api_hash", palette.fg_muted)
    _field(painter, palette, QRectF(90, 36, 136, 22), "0123...cdef (32)")
    painter.drawPixmap(QPointF(14, 66), icon_pixmap("copy", palette.accent, 16))
    _text(painter, QRectF(36, 64, 190, 20), "api_id, api_hash", palette.fg_secondary)


_DRAWERS: Final = {
    "site": _site,
    "phone": _phone,
    "code": _code,
    "tools": _tools,
    "form": _form,
    "create": _create,
    "keys": _keys,
}


class SchemeArt(QWidget):
    def __init__(self, kit: UiKit, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if kind not in KINDS:
            raise ValueError(f"unknown scheme: {kind}")
        self.kit = kit
        self.kind = kind
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        bind_kit(kit, theme=self.update, zoom=self._resize)
        self._resize()

    def _resize(self) -> None:
        self.setFixedSize(self.kit.px(BOX_WIDTH), self.kit.px(BOX_HEIGHT))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        palette = self.kit.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(self.width() / BOX_WIDTH, self.height() / BOX_HEIGHT)
        _box(
            painter,
            QRectF(0.5, 0.5, BOX_WIDTH - 1, BOX_HEIGHT - 1),
            palette.surface_sunken,
            palette.border,
            8,
        )
        _DRAWERS[self.kind](painter, palette)
        painter.end()
