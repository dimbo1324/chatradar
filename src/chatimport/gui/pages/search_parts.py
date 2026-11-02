"""Small widgets of the Search page: the query box, the sticky chat menu, the skeleton, the list."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractItemView, QListView, QMenu, QWidget

from chatimport.gui.i18n import tr
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.search_field import SearchField
from chatimport.search_types import IndexState

if TYPE_CHECKING:
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QPaintEvent, QResizeEvent

    from chatimport.gui.kit import UiKit
    from chatimport.gui.pages.search_delegate import SearchDelegate

SKELETON_ROWS: Final = 5
RELAYOUT_MS: Final = 60


def notice_keys(
    error: bool, missing: bool, state: IndexState | None, searching: bool
) -> tuple[str, str, str]:
    """Icon, title key and text key of the block that stands in for the list."""
    if error:
        return "alert", "find.state.error.title", "find.state.error.text"
    if missing:
        return "disk", "find.state.missing.title", "find.state.missing.text"
    if state is IndexState.DISABLED:
        return "ban", "find.state.disabled.title", "find.state.disabled.text"
    if searching:
        return "search", "find.state.nothing.title", "find.state.nothing.text"
    if state is IndexState.BUILDING:
        return "hourglass", "find.state.building.title", "find.state.building.text"
    return "search", "find.state.idle.title", "find.state.idle.text"


class QueryField(SearchField):
    """The search box: Enter and Down go to the next result, Shift+Enter and Up to the previous."""

    next_requested = Signal()
    previous_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            (self.previous_requested if shift else self.next_requested).emit()
            event.accept()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            (self.next_requested if key == Qt.Key.Key_Down else self.previous_requested).emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _retranslate(self) -> None:
        super()._retranslate()
        self.setPlaceholderText(tr("find.placeholder"))
        self.setAccessibleName(tr("find.placeholder"))


class StickyMenu(QMenu):
    """A menu whose checkable entries toggle without closing it (multi-select)."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():  # pyright: ignore[reportUnnecessaryComparison]
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class Skeleton(QWidget):
    """Grey placeholder rows shown while the first page is on its way."""

    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kit = kit
        bind_kit(kit, theme=self.update, zoom=self.update)

    def sizeHint(self) -> QSize:
        return QSize(self.kit.px(320), self.kit.px(220))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.kit.palette.surface_active))
        pad = self.kit.px(SPACE[5])
        bar = self.kit.px(SPACE[4])
        gap = self.kit.px(SPACE[3])
        block = bar * 3 + gap * 4 + self.kit.px(SPACE[5])
        width = max(self.width() - 2 * pad, 1)
        for row in range(SKELETON_ROWS):
            top = row * block + pad
            if top > self.height():
                break
            for line, share in enumerate((0.34, 0.92, 0.7)):
                painter.drawRoundedRect(
                    QRectF(pad, top + line * (bar + gap), width * share, bar), bar / 2, bar / 2
                )
        event.accept()


class ResultsView(QListView):
    """The result list: it tells its delegate how wide a row is and re-lays rows on resize."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setUniformItemSizes(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setMouseTracking(True)
        self._rows: SearchDelegate | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RELAYOUT_MS)
        self._timer.timeout.connect(self._relayout)

    def use_delegate(self, delegate: SearchDelegate) -> None:
        self._rows = delegate
        self.setItemDelegate(delegate)

    def _relayout(self) -> None:
        if self._rows is not None:
            self._rows.available_width = self.viewport().width()
        self.doItemsLayout()

    def sync_width(self) -> None:
        self._relayout()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._rows is not None:
            self._rows.available_width = self.viewport().width()
        self._timer.start()
