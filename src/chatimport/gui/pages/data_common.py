"""Plumbing shared by the cards of the Data page: state, confirmation, selectors, cell painting."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.i18n import tr
from chatimport.gui.models.data_models import (
    MEDIA_SHARE_ROLE,
    SHARE_ROLE,
    TONE_ROLE,
    IssueColumn,
    UsageColumn,
)
from chatimport.gui.models.presentation import ChipSpec
from chatimport.gui.pages.paint import chip_height, draw_chip
from chatimport.gui.pages.support import MainThreadRunner, notify
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.labels import make_label

if TYPE_CHECKING:
    from pathlib import Path

    from PySide6.QtCore import QModelIndex, QPersistentModelIndex

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from chatimport.usage import ArchiveUsage

type _Index = QModelIndex | QPersistentModelIndex

TABLE_MAX_ROWS: Final = 8
SEVERITY_ICONS: Final = {"danger": "x-circle", "warning": "alert", "info": "info"}


class DataEnv(QObject):
    """What every card shares: the data root, latest usage, runner, toasts and confirmations."""

    usage_changed = Signal()
    root_changed = Signal()
    request_usage = Signal()

    def __init__(self, gui: GuiContext, page: QWidget) -> None:
        super().__init__(page)
        self.gui = gui
        self.page = page
        self.runner = MainThreadRunner(self)
        self.root: Path = gui.current.root
        self.usage: ArchiveUsage | None = None

    def set_usage(self, usage: ArchiveUsage) -> None:
        self.usage = usage
        self.usage_changed.emit()

    def set_root(self, root: Path) -> None:
        self.root = root
        self.usage = None
        self.root_changed.emit()
        self.request_usage.emit()

    def chats(self) -> list[tuple[int, str]]:
        """(chat id, title) of every readable chat in the latest usage, by title."""
        if self.usage is None:
            return []
        pairs = [
            (chat.chat_id, chat.title or str(chat.chat_id))
            for chat in self.usage.chats
            if chat.chat_id is not None
        ]
        return sorted(pairs, key=lambda pair: pair[1].casefold())

    def toast(self, tone: Tone, message: str) -> None:
        notify(self.page, tone, message)

    def unavailable(self) -> None:
        self.toast("warning", tr("data.unavailable"))

    def confirm(self, title: str, text: str, accept: str, *, danger: bool = True) -> bool:
        box = QMessageBox(self.page)
        box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(text)
        yes = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is yes

    def open_folder(self, folder: Path) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.toast("warning", tr("data.folder.toast.opened_failed"))


class ChatSelector(QComboBox):
    """A combo box of chats; with `allow_all` the first entry means "every chat" (id None)."""

    def __init__(self, *, allow_all: bool) -> None:
        super().__init__()
        self._allow_all = allow_all
        self._chats: list[tuple[int, str]] = []
        self.setMinimumContentsLength(12)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

    def set_chats(self, chats: list[tuple[int, str]]) -> None:
        current = self.chat_id()
        self._chats = chats
        self.rebuild(current)

    def rebuild(self, keep: int | None = None) -> None:
        wanted = self.chat_id() if keep is None else keep
        self.blockSignals(True)
        self.clear()
        if self._allow_all:
            self.addItem(tr("data.all_chats"), None)
        for chat_id, title in self._chats:
            self.addItem(title, chat_id)
        index = self.findData(wanted)
        self.setCurrentIndex(max(index, 0))
        self.setEnabled(self.count() > 0)
        self.blockSignals(False)
        self.currentIndexChanged.emit(self.currentIndex())

    def chat_id(self) -> int | None:
        data = self.currentData()
        return data if isinstance(data, int) else None

    def title(self) -> str:
        return self.currentText()


def column(parent: QWidget, *, spacing: int = 0) -> QVBoxLayout:
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    return layout


class FieldRow(QWidget):
    """A small caption above a control, so toolbars of cards line up."""

    def __init__(self, kit: UiKit, caption: str, control: QWidget) -> None:
        super().__init__()
        self._kit = kit
        self._caption = make_label(caption, "caption")
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.addWidget(self._caption)
        self._column.addWidget(control)
        bind_kit(kit, zoom=self._restyle)
        self._restyle()

    def set_caption(self, text: str) -> None:
        self._caption.setText(text)

    def _restyle(self) -> None:
        self._column.setSpacing(self._kit.px(SPACE[2]))


def toolbar(kit: UiKit) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(kit.px(SPACE[4]))
    return row


def fit_table(view: QTableView, kit: UiKit, rows: int) -> None:
    """Size a table to its rows (up to `TABLE_MAX_ROWS`) so the cards stay compact."""
    shown = min(max(rows, 1), TABLE_MAX_ROWS)
    row_height = view.verticalHeader().defaultSectionSize()
    frame = 2 * view.frameWidth() + kit.px(2)
    view.setFixedHeight(view.horizontalHeader().height() + shown * row_height + frame)


def prepare_table(view: QTableView) -> None:
    view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    view.setWordWrap(False)
    view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)


class _CellDelegate(QStyledItemDelegate):
    def __init__(self, kit: UiKit) -> None:
        super().__init__()
        self.kit = kit

    def paint_background(
        self, painter: QPainter, option: QStyleOptionViewItem, index: _Index
    ) -> QRect:
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
        return option.rect.adjusted(pad, 0, -pad, 0)


class ShareBarDelegate(_CellDelegate):
    """The proportional bar of a chat: its length is relative to the largest chat, the media part
    of it is drawn in the accent-soft colour next to the messages part."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        if index.column() != UsageColumn.SHARE:
            super().paint(painter, option, index)
            return
        area = self.paint_background(painter, option, index)
        share = index.data(SHARE_ROLE)
        media = index.data(MEDIA_SHARE_ROLE)
        if not isinstance(share, float) or not isinstance(media, float):
            return
        palette = self.kit.palette
        height = self.kit.px(SPACE[3])
        track = QRectF(area.left(), area.center().y() - height / 2, area.width(), height)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.surface_active))
        painter.drawRoundedRect(track, height / 2, height / 2)
        total = max(track.width() * share, min(track.width(), float(height)))
        messages = total * (1 - media)
        painter.setClipRect(QRectF(track.left(), track.top(), total, height))
        painter.setBrush(QColor(palette.accent))
        painter.drawRoundedRect(
            QRectF(track.left(), track.top(), total, height), height / 2, height / 2
        )
        if media > 0:
            painter.setBrush(QColor(palette.live))
            painter.drawRect(QRectF(track.left() + messages, track.top(), total - messages, height))
        painter.restore()


class SeverityDelegate(_CellDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        if index.column() != IssueColumn.SEVERITY:
            super().paint(painter, option, index)
            return
        area = self.paint_background(painter, option, index)
        tone = index.data(TONE_ROLE)
        if tone not in SEVERITY_ICONS:
            return
        spec = ChipSpec(str(index.data()), tone, SEVERITY_ICONS[tone])
        top = area.top() + (area.height() - chip_height(self.kit)) // 2
        painter.save()
        painter.setClipRect(option.rect)
        draw_chip(painter, self.kit, spec, area.left(), top, option.font)
        painter.restore()


ZERO_WIDTH_SPACE: Final = chr(0x200B)


def breakable(path: str) -> str:
    """The path with a zero-width break after each separator, so a wrapping label can wrap it."""
    for separator in ("\\", "/"):
        path = path.replace(separator, separator + ZERO_WIDTH_SPACE)
    return path
