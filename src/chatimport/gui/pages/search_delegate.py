"""Paints a search result: title, exact moment, age, edited pill and highlighted text."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QModelIndex, QPointF, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QTextCharFormat,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from chatimport.gui.format import format_ago, format_exact
from chatimport.gui.i18n import tr
from chatimport.gui.models.presentation import ChipSpec
from chatimport.gui.models.search_model import HIT_ROLE
from chatimport.gui.models.search_spans import ELLIPSIS, Span, snippet
from chatimport.gui.pages.paint import chip_height, chip_width, draw_chip, token_font
from chatimport.gui.strings import current_language
from chatimport.gui.tokens import SPACE
from chatimport.search_types import SearchHit

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtCore import QPersistentModelIndex

    from chatimport.gui.kit import UiKit

type _Index = QModelIndex | QPersistentModelIndex

MAX_LINES: Final = 4
HIGHLIGHT_ALPHA: Final = 80
MIN_WIDTH: Final = 120


def _formats(spans: tuple[Span, ...], color: QColor) -> list[QTextLayout.FormatRange]:
    ranges: list[QTextLayout.FormatRange] = []
    for start, end in spans:
        fmt = QTextCharFormat()
        fmt.setBackground(color)
        item = QTextLayout.FormatRange()
        item.start = start
        item.length = end - start
        item.format = fmt
        ranges.append(item)
    return ranges


def _lay_out(
    text: str, spans: tuple[Span, ...], font: QFont, width: int, color: QColor
) -> tuple[QTextLayout, int, int]:
    """The layout, its height and how many characters fit in `MAX_LINES` lines."""
    layout = QTextLayout(text, font)
    wrap = QTextOption()
    wrap.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(wrap)
    layout.setFormats(_formats(spans, color))
    layout.beginLayout()
    top = 0.0
    lines = 0
    fitted = 0
    while lines < MAX_LINES:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        line.setPosition(QPointF(0.0, top))
        top += line.height()
        lines += 1
        fitted = line.textStart() + line.textLength()
    layout.endLayout()
    return layout, int(top + 0.999), fitted


def body_layout(
    text: str, spans: tuple[Span, ...], font: QFont, width: int, color: QColor
) -> tuple[QTextLayout, int]:
    """Lay the text out in at most `MAX_LINES` lines; a longer text ends with an ellipsis."""
    layout, height, fitted = _lay_out(text, spans, font, width, color)
    if fitted >= len(text):
        return layout, height
    cut = max(fitted - 1, 1)
    clipped = text[:cut].rstrip() + ELLIPSIS
    kept = tuple((a, min(b, cut)) for a, b in spans if a < cut)
    layout, height, _ = _lay_out(clipped, kept, font, width, color)
    return layout, height


def utc_now() -> datetime:
    return datetime.now(UTC)


class SearchDelegate(QStyledItemDelegate):
    def __init__(self, kit: UiKit, clock: Callable[[], datetime] = utc_now) -> None:
        super().__init__()
        self.kit = kit
        self.clock = clock
        self.available_width = 0
        self.needle = ""

    def _pad(self) -> int:
        return self.kit.px(SPACE[5])

    def _hit(self, index: _Index) -> SearchHit | None:
        value = index.data(HIT_ROLE)
        return value if isinstance(value, SearchHit) else None

    def _highlight(self) -> QColor:
        color = QColor(self.kit.palette.accent)
        color.setAlpha(HIGHLIGHT_ALPHA)
        return color

    def _fonts(self, base: QFont) -> tuple[QFont, QFont, QFont]:
        return (
            token_font(base, self.kit, "base", "semibold"),
            token_font(base, self.kit, "xs"),
            token_font(base, self.kit, "base"),
        )

    def _body(self, hit: SearchHit, font: QFont, width: int) -> tuple[QTextLayout, int]:
        piece = snippet(hit.text, self.needle)
        return body_layout(piece.text, piece.spans, font, width, self._highlight())

    def _line_height(self, base: QFont) -> int:
        title, meta, _body = self._fonts(base)
        return max(QFontMetrics(title).height(), QFontMetrics(meta).height(), chip_height(self.kit))

    def _edited_spec(self) -> ChipSpec:
        return ChipSpec(tr("find.edited"), "muted", "refresh")

    def _chip_space(self, base: QFont, hit: SearchHit) -> int:
        if not hit.edited:
            return 0
        font = token_font(base, self.kit, "xs", "medium")
        return chip_width(self.kit, self._edited_spec(), font) + self.kit.px(SPACE[4])

    def _is_stacked(self, base: QFont, hit: SearchHit, width: int) -> bool:
        """The exact moment drops to its own line when title, moment and pill do not fit."""
        title, meta, _body = self._fonts(base)
        need = (
            QFontMetrics(title).horizontalAdvance(hit.chat_title)
            + QFontMetrics(meta).horizontalAdvance(self.meta_text(hit))
            + self._chip_space(base, hit)
            + self.kit.px(SPACE[5])
        )
        return need > width

    def _head_height(self, base: QFont, hit: SearchHit, width: int) -> int:
        first = self._line_height(base)
        if not self._is_stacked(base, hit, width):
            return first
        return first + QFontMetrics(self._fonts(base)[1]).height() + self.kit.px(SPACE[1])

    def _inner_width(self, option_width: int) -> int:
        full = self.available_width or option_width
        return max(full - 2 * self._pad(), MIN_WIDTH)

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        hit = self._hit(index)
        width = self.available_width or option.rect.width()
        if hit is None:
            return super().sizeHint(option, index)
        _title, _meta, body_font = self._fonts(option.font)
        inner = self._inner_width(option.rect.width())
        _layout, body = self._body(hit, body_font, inner)
        vertical = self.kit.px(SPACE[4])
        gap = self.kit.px(SPACE[2])
        head = self._head_height(option.font, hit, inner)
        return QSize(width, 2 * vertical + head + gap + body)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        hit = self._hit(index)
        if hit is None:
            super().paint(painter, option, index)
            return
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        background.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget
            )
        painter.save()
        painter.setClipRect(option.rect)
        pad = self._pad()
        area = option.rect.adjusted(pad, self.kit.px(SPACE[4]), -pad, 0)
        head = self._head_height(option.font, hit, area.width())
        self._paint_head(painter, option, area, head, hit)
        top = area.top() + head + self.kit.px(SPACE[2])
        self._paint_body(painter, option, area, top, hit)
        painter.setPen(QColor(self.kit.palette.border))
        painter.drawLine(
            option.rect.left(), option.rect.bottom(), option.rect.right(), option.rect.bottom()
        )
        painter.restore()

    def meta_text(self, hit: SearchHit) -> str:
        age = (self.clock() - hit.date).total_seconds()
        return f"{format_exact(hit.date)} · {format_ago(max(age, 0.0), current_language())}"

    def _paint_head(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        area: QRect,
        head: int,
        hit: SearchHit,
    ) -> None:
        palette = self.kit.palette
        title_font, meta_font, _body = self._fonts(option.font)
        stacked = self._is_stacked(option.font, hit, area.width())
        first = self._line_height(option.font)
        gap = self.kit.px(SPACE[4])
        right = area.right()
        if hit.edited:
            spec = self._edited_spec()
            chip_font = token_font(option.font, self.kit, "xs", "medium")
            width = chip_width(self.kit, spec, chip_font)
            top = area.top() + (first - chip_height(self.kit)) // 2
            draw_chip(painter, self.kit, spec, right - width + 1, top, option.font)
            right -= width + gap
        meta = self.meta_text(hit)
        meta_metrics = QFontMetrics(meta_font)
        painter.setFont(meta_font)
        painter.setPen(QColor(palette.fg_muted))
        if stacked:
            meta_rect = QRect(area.left(), area.top() + first, area.width(), head - first)
            align = Qt.AlignmentFlag.AlignLeft
            shown = meta_metrics.elidedText(meta, Qt.TextElideMode.ElideRight, area.width())
            title_right = right
        else:
            meta_width = meta_metrics.horizontalAdvance(meta)
            meta_rect = QRect(right - meta_width + 1, area.top(), meta_width, first)
            align = Qt.AlignmentFlag.AlignRight
            shown = meta
            title_right = meta_rect.left() - gap
        painter.drawText(meta_rect, int(align | Qt.AlignmentFlag.AlignVCenter), shown)
        title_width = max(title_right - area.left(), 1)
        painter.setFont(title_font)
        painter.setPen(QColor(palette.fg))
        painter.drawText(
            QRect(area.left(), area.top(), title_width, first),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(title_font).elidedText(
                hit.chat_title, Qt.TextElideMode.ElideRight, title_width
            ),
        )

    def _paint_body(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, top: int, hit: SearchHit
    ) -> None:
        _title, _meta, body_font = self._fonts(option.font)
        layout, _height = self._body(hit, body_font, max(area.width(), 1))
        painter.setPen(QColor(self.kit.palette.fg_secondary))
        painter.setFont(body_font)
        layout.draw(painter, QPointF(area.left(), top))
