"""Hand-painting helpers for table cells: pills, thin progress bars, text in a token font."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath

from chatimport.gui.icons import icon_pixmap
from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import LAYOUT, SPACE, TEXT, WEIGHT

if TYPE_CHECKING:
    from PySide6.QtCore import QRect

    from chatimport.gui.kit import UiKit
    from chatimport.gui.models.presentation import ChipSpec

BAR_HEIGHT: Final = 4
SHEEN_SHARE: Final = 0.35
INDETERMINATE_SHARE: Final = 0.38


def token_font(base: QFont, kit: UiKit, size: str, weight: str = "normal") -> QFont:
    font = QFont(base)
    font.setPixelSize(kit.px(TEXT[size]))
    font.setWeight(QFont.Weight(WEIGHT[weight]))
    return font


def chip_height(kit: UiKit) -> int:
    return kit.px(LAYOUT["icon_lg"] + 2)


def chip_width(kit: UiKit, spec: ChipSpec, font: QFont) -> int:
    pad = kit.px(SPACE[4])
    icon_size = kit.px(LAYOUT["icon_sm"])
    gap = kit.px(SPACE[2] + 1)
    return pad * 2 + icon_size + gap + QFontMetrics(font).horizontalAdvance(spec.text)


def draw_chip(
    painter: QPainter, kit: UiKit, spec: ChipSpec, left: int, top: int, base_font: QFont
) -> int:
    """Draw the pill with its top-left at (`left`, `top`); returns its width."""
    font = token_font(base_font, kit, "xs", "medium")
    width = chip_width(kit, spec, font)
    height = chip_height(kit)
    background, border, foreground = tone_colors(kit.palette, spec.tone)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(left + 0.5, top + 0.5, width - 1, height - 1)
    painter.setBrush(QColor(background))
    painter.setPen(QColor(border))
    painter.drawRoundedRect(rect, height / 2, height / 2)
    pad = kit.px(SPACE[4])
    size = kit.px(LAYOUT["icon_sm"])
    pixmap = icon_pixmap(spec.icon, foreground, size)
    painter.drawPixmap(QPointF(left + pad, top + (height - size) / 2), pixmap)
    painter.setFont(font)
    painter.setPen(QColor(foreground))
    text_left = left + pad + size + kit.px(SPACE[2] + 1)
    painter.drawText(
        QRectF(text_left, top, width, height),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        spec.text,
    )
    painter.restore()
    return width


def draw_bar(
    painter: QPainter,
    kit: UiKit,
    rect: QRect,
    fraction: float | None,
    color: str,
    phase: float,
) -> None:
    """A thin rounded bar; a moving sheen shows it is alive, `None` sweeps a block instead."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    bounds = QRectF(rect)
    radius = bounds.height() / 2
    clip = QPainterPath()
    clip.addRoundedRect(bounds, radius, radius)
    painter.setClipPath(clip)
    painter.fillRect(bounds, QColor(kit.palette.surface_active))
    fill = QColor(color)
    if fraction is None:
        width = bounds.width() * INDETERMINATE_SHARE
        left = bounds.left() - width + (bounds.width() + width) * phase
        painter.fillRect(QRectF(left, bounds.top(), width, bounds.height()), fill)
    else:
        filled = QRectF(bounds.left(), bounds.top(), bounds.width() * fraction, bounds.height())
        painter.fillRect(filled, fill)
        sheen_width = max(filled.width() * SHEEN_SHARE, bounds.height() * 4)
        left = filled.left() - sheen_width + (filled.width() + sheen_width) * phase
        gradient = QLinearGradient(left, 0, left + sheen_width, 0)
        clear, light = QColor(255, 255, 255, 0), QColor(255, 255, 255, 110)
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(0.5, light)
        gradient.setColorAt(1.0, clear)
        painter.setClipRect(filled, Qt.ClipOperation.IntersectClip)
        painter.fillRect(QRectF(left, bounds.top(), sheen_width, bounds.height()), gradient)
    painter.restore()


def draw_dot(painter: QPainter, kit: UiKit, color: str, left: int, center_y: int) -> int:
    side = kit.px(7)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(left, center_y - side / 2, side, side))
    painter.restore()
    return side
