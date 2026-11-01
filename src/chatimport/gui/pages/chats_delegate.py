"""Paints the chats table cells: titles with ids, pills, the live progress bar, the age."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from chatimport.gui.format import format_count, format_percent
from chatimport.gui.models.chats_model import ROW_ROLE, ChatsTableModel, Column
from chatimport.gui.models.presentation import (
    history_chip,
    history_detail,
    span_text,
    status_chip,
)
from chatimport.gui.pages.paint import (
    BAR_HEIGHT,
    chip_height,
    draw_bar,
    draw_chip,
    draw_dot,
    token_font,
)
from chatimport.gui.strings import current_language
from chatimport.gui.theme import freshness_color
from chatimport.gui.tokens import SPACE
from chatimport.runtime import BackfillState

if TYPE_CHECKING:
    from PySide6.QtCore import QPersistentModelIndex

    from chatimport.gui.kit import UiKit
    from chatimport.gui.models.snapshot import ChatRow

type _Index = QModelIndex | QPersistentModelIndex


class ChatsDelegate(QStyledItemDelegate):
    def __init__(self, kit: UiKit, model: ChatsTableModel) -> None:
        super().__init__()
        self.kit = kit
        self._model = model
        self.phase = 0.0

    def _row(self, index: _Index) -> ChatRow | None:
        value = index.data(ROW_ROLE)
        return value if hasattr(value, "chat_id") else None

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        row = self._row(index)
        if row is None:
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
        pad = self.kit.px(SPACE[4])
        area = option.rect.adjusted(pad, 0, -pad, 0)
        painter.save()
        painter.setClipRect(option.rect)
        column = Column(index.column())
        if column is Column.CHAT:
            self._paint_chat(painter, option, area, row)
        elif column is Column.STATUS:
            self._paint_status(painter, option, area, row)
        elif column is Column.HISTORY:
            self._paint_history(painter, option, area, row)
        elif column is Column.LAST_MESSAGE:
            self._paint_last(painter, option, area, row, str(index.data()))
        else:
            self._paint_plain(painter, option, area, row, column)
        painter.restore()

    def _paint_chat(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, row: ChatRow
    ) -> None:
        palette = self.kit.palette
        if row.has_problem:
            tone = palette.danger if not row.has_access or row.error else palette.warning
            strip = QRect(
                option.rect.left(), option.rect.top() + 6, self.kit.px(3), option.rect.height() - 12
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tone))
            painter.drawRoundedRect(strip, 1.5, 1.5)
        title_font = token_font(option.font, self.kit, "base", "medium")
        id_font = token_font(option.font, self.kit, "xs")
        title_h = QFontMetrics(title_font).height()
        id_h = QFontMetrics(id_font).height()
        top = area.top() + (area.height() - title_h - id_h) // 2
        title_rect = QRect(area.left(), top, area.width(), title_h)
        id_rect = QRect(area.left(), top + title_h, area.width(), id_h)
        painter.setFont(title_font)
        painter.setPen(QColor(palette.fg))
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            QFontMetrics(title_font).elidedText(
                row.title, Qt.TextElideMode.ElideRight, area.width()
            ),
        )
        painter.setFont(id_font)
        painter.setPen(QColor(palette.fg_muted))
        painter.drawText(
            id_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            str(row.chat_id),
        )

    def _paint_status(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, row: ChatRow
    ) -> None:
        spec = status_chip(row, current_language())
        top = area.top() + (area.height() - chip_height(self.kit)) // 2
        draw_chip(painter, self.kit, spec, area.left(), top, option.font)

    def _paint_history(
        self, painter: QPainter, option: QStyleOptionViewItem, area: QRect, row: ChatRow
    ) -> None:
        language = current_language()
        info = row.backfill
        spec = history_chip(row, language)
        height = chip_height(self.kit)
        running = info.state is BackfillState.RUNNING
        gap = self.kit.px(SPACE[2])
        block = height + (gap + self.kit.px(BAR_HEIGHT) if running else 0)
        top = area.top() + (area.height() - block) // 2
        width = draw_chip(painter, self.kit, spec, area.left(), top, option.font)
        small = token_font(option.font, self.kit, "xs")
        painter.setFont(small)
        painter.setPen(QColor(self.kit.palette.fg_muted))
        detail = history_detail(row, self._model.now(), language)
        left = area.left() + width + self.kit.px(SPACE[3])
        if detail:
            painter.drawText(
                QRect(left, top, max(area.right() - left, 0), height),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                QFontMetrics(small).elidedText(
                    detail, Qt.TextElideMode.ElideRight, area.right() - left
                ),
            )
        if running:
            if info.progress is not None:
                percent = format_percent(info.progress, language)
                painter.drawText(
                    QRect(left, top, max(area.right() - left, 0), height),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    percent,
                )
            bar = QRect(area.left(), top + height + gap, area.width(), self.kit.px(BAR_HEIGHT))
            draw_bar(painter, self.kit, bar, info.progress, self.kit.palette.live, self.phase)

    def _paint_last(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        area: QRect,
        row: ChatRow,
        text: str,
    ) -> None:
        palette = self.kit.palette
        color = freshness_color(palette, self._model.freshness(row))
        left = area.left()
        left += draw_dot(painter, self.kit, color, left, area.center().y()) + self.kit.px(SPACE[3])
        painter.setFont(token_font(option.font, self.kit, "base", "medium"))
        painter.setPen(QColor(color))
        metrics = painter.fontMetrics()
        painter.drawText(
            QRect(left, area.top(), max(area.right() - left, 0), area.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(area.right() - left, 0)),
        )

    def _paint_plain(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        area: QRect,
        row: ChatRow,
        column: Column,
    ) -> None:
        palette = self.kit.palette
        language = current_language()
        if column is Column.MESSAGES:
            text = format_count(row.records, language)
            flags, color = Qt.AlignmentFlag.AlignRight, palette.fg
            painter.setFont(token_font(option.font, self.kit, "base"))
        else:
            text = span_text(row)
            flags, color = Qt.AlignmentFlag.AlignLeft, palette.fg_secondary
            painter.setFont(token_font(option.font, self.kit, "sm"))
        painter.setPen(QColor(color))
        painter.drawText(area, int(flags | Qt.AlignmentFlag.AlignVCenter), text)
