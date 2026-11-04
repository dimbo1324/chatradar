"""Paints the log table: level pills, tinted warning and error rows, monospace text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from chatimport.gui.models.log_model import RECORD_ROLE, Column
from chatimport.gui.models.log_parser import Level, LogRecord
from chatimport.gui.models.presentation import ChipSpec
from chatimport.gui.pages.paint import chip_height, draw_chip, token_font
from chatimport.gui.strings import current_language, translate
from chatimport.gui.tokens import FONT_MONO, SPACE

if TYPE_CHECKING:
    from PySide6.QtCore import QPersistentModelIndex

    from chatimport.gui.kit import UiKit
    from chatimport.gui.widgets.base import Tone

type _Index = QModelIndex | QPersistentModelIndex

LEVEL_CHIPS: Final[dict[Level, tuple[Tone, str]]] = {
    Level.DEBUG: ("muted", "hash"),
    Level.INFO: ("info", "info"),
    Level.WARNING: ("warning", "alert"),
    Level.ERROR: ("danger", "x-circle"),
    Level.CRITICAL: ("danger", "ban"),
}
WRAP_FLAGS: Final = int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere)
STRIP_WIDTH: Final = 3
TINT_ALPHA: Final = 150


def mono_font(base: QFont, kit: UiKit, size: str = "sm") -> QFont:
    font = token_font(base, kit, size)
    font.setFamilies(list(FONT_MONO))
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class LogDelegate(QStyledItemDelegate):
    def __init__(self, kit: UiKit) -> None:
        super().__init__()
        self.kit = kit
        self.wrap = False
        self.message_width = 400

    def _pad(self) -> int:
        return self.kit.px(SPACE[4])

    def _record(self, index: _Index) -> LogRecord | None:
        value = index.data(RECORD_ROLE)
        return value if isinstance(value, LogRecord) else None

    def _tint(self, record: LogRecord) -> str | None:
        palette = self.kit.palette
        if record.level >= Level.ERROR:
            return palette.danger_soft
        if record.level is Level.WARNING:
            return palette.warning_soft
        return None

    def wrapped_height(self, record: LogRecord, font: QFont, width: int) -> int:
        area = QRect(0, 0, max(width, 1), 100_000)
        return QFontMetrics(font).boundingRect(area, WRAP_FLAGS, record.message).height()

    def row_height(self, record: LogRecord, font: QFont, minimum: int) -> int:
        """Height of a wrapped row: the message laid out in the message column."""
        usable = self.message_width - 2 * self._pad()
        text = self.wrapped_height(record, mono_font(font, self.kit), usable)
        return max(minimum, text + 2 * self.kit.px(SPACE[3]))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        record = self._record(index)
        if record is None:
            super().paint(painter, option, index)
            return
        tint = self._tint(record)
        if tint is not None and not option.state & QStyle.StateFlag.State_Selected:
            wash = QColor(tint)
            wash.setAlpha(TINT_ALPHA)
            painter.fillRect(option.rect, wash)
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        background.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, background, painter, option.widget
            )
        pad = self._pad()
        area = option.rect.adjusted(pad, 0, -pad, 0)
        painter.save()
        painter.setClipRect(option.rect)
        column = Column(index.column())
        if column is Column.TIME:
            self._paint_time(painter, option, area, record, str(index.data()))
        elif column is Column.LEVEL:
            self._paint_level(painter, option, area, record)
        elif column is Column.SOURCE:
            self._paint_text(painter, option, area, record.source, self.kit.palette.fg_secondary)
        else:
            self._paint_message(painter, option, area, record)
        painter.restore()

    def _row_top(self, area: QRect, height: int) -> int:
        return (
            area.top() + self.kit.px(SPACE[3])
            if self.wrap
            else area.top() + (area.height() - height) // 2
        )

    def _paint_time(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        area: QRect,
        record: LogRecord,
        text: str,
    ) -> None:
        if record.level >= Level.WARNING:
            tone = (
                self.kit.palette.danger if record.level >= Level.ERROR else self.kit.palette.warning
            )
            strip = QRect(
                option.rect.left(),
                option.rect.top(),
                self.kit.px(STRIP_WIDTH),
                option.rect.height(),
            )
            painter.fillRect(strip, QColor(tone))
        self._paint_text(painter, option, area, text, self.kit.palette.fg_muted)

    def _paint_text(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, text: str, color: str
    ) -> None:
        font = mono_font(option.font, self.kit)
        painter.setFont(font)
        painter.setPen(QColor(color))
        metrics = QFontMetrics(font)
        top = self._row_top(area, metrics.height())
        painter.drawText(
            QRect(area.left(), top, area.width(), metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, area.width()),
        )

    def _paint_level(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, record: LogRecord
    ) -> None:
        tone, icon = LEVEL_CHIPS[record.level]
        text = translate(current_language(), f"log.level.{record.level.name.lower()}")
        height = chip_height(self.kit)
        top = self._row_top(area, height)
        draw_chip(painter, self.kit, ChipSpec(text, tone, icon), area.left(), top, option.font)

    def _paint_message(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, record: LogRecord
    ) -> None:
        palette = self.kit.palette
        font = mono_font(option.font, self.kit)
        color = palette.fg_muted if record.level is Level.DEBUG else palette.fg
        painter.setFont(font)
        painter.setPen(QColor(color))
        metrics = QFontMetrics(font)
        if self.wrap:
            rect = QRect(area.left(), area.top() + self.kit.px(SPACE[3]), area.width(), 100_000)
            painter.drawText(rect, WRAP_FLAGS | int(Qt.AlignmentFlag.AlignTop), record.message)
            return
        tag = ""
        if record.has_traceback:
            tag = f"{translate(current_language(), 'log.traceback')} +{record.line_count - 1}"
        small = token_font(option.font, self.kit, "xs")
        tag_width = QFontMetrics(small).horizontalAdvance(tag) + self._pad() if tag else 0
        top = self._row_top(area, metrics.height())
        text_width = max(area.width() - tag_width, 0)
        painter.drawText(
            QRect(area.left(), top, text_width, metrics.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(record.message, Qt.TextElideMode.ElideRight, text_width),
        )
        if tag:
            painter.setFont(small)
            painter.setPen(QColor(palette.fg_muted))
            painter.drawText(
                QRect(area.left(), area.top(), area.width(), area.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                tag,
            )
