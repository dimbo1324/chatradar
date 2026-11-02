from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QEvent, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QTableView, QWidget

from chatimport.gui.models.log_model import RECORD_ROLE, Column, LogModel
from chatimport.gui.models.log_parser import Level, LogRecord
from chatimport.gui.pages.log_delegate import LogDelegate, mono_font
from chatimport.gui.pages.log_widgets import DetailPane, FloatingHost, InlineSwitch
from chatimport.gui.widgets.button import Button

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext

MOMENT = datetime(2026, 10, 31, 20, 0, 0, tzinfo=UTC)


def record(level: Level, message: str = "hello", detail: str = "") -> LogRecord:
    return LogRecord(MOMENT, level, "chatimport.worker", message, detail)


def release(widget: QWidget, button: Qt.MouseButton) -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(1, 1),
        QPointF(1, 1),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def test_inline_switch_label_click(gui: GuiContext, qapp: object) -> None:
    inline = InlineSwitch(gui.kit, "label")
    seen: list[bool] = []
    inline.toggled.connect(seen.append)
    label = inline._label  # pyright: ignore[reportPrivateUsage]
    assert inline.eventFilter(label, release(label, Qt.MouseButton.RightButton)) is False
    assert inline.eventFilter(label, release(label, Qt.MouseButton.LeftButton)) is True
    assert seen == [True]
    assert inline.eventFilter(inline, QEvent(QEvent.Type.Show)) is False
    inline.set_text("other", "tip")
    inline.set_checked(False)
    assert not inline.is_checked()


def test_detail_pane(gui: GuiContext, qapp: object) -> None:
    pane = DetailPane(gui.kit)
    pane.show_record(record(Level.ERROR, detail="trace"))
    assert pane.toPlainText().endswith("trace")
    pane.set_wrap(True)
    assert pane.lineWrapMode().name == "WidgetWidth"
    pane.set_wrap(False)
    pane.show_record(None)
    assert pane.toPlainText() == ""


def test_floating_host_places_button(gui: GuiContext, qapp: object) -> None:
    jump = Button(gui.kit, "go")
    host = FloatingHost(gui.kit, QWidget(), jump)
    host.resize(300, 200)
    host.show()
    jump.show()
    host.resize(400, 300)
    assert jump.x() + jump.width() < 400
    assert jump.y() + jump.height() < 300


def paint(delegate: LogDelegate, view: QTableView, row: int, column: int) -> None:
    image = QImage(400, 60, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 400, 40 if column != Column.MESSAGE else 60)
    option.widget = view
    option.font = view.font()
    delegate.paint(painter, option, view.model().index(row, column))
    painter.end()


def test_delegate_paints_every_column_and_level(gui: GuiContext, qapp: object) -> None:
    model = LogModel("en")
    model.append(
        [
            record(Level.DEBUG),
            record(Level.INFO),
            record(Level.WARNING),
            record(Level.ERROR, detail="a\nb"),
            record(Level.CRITICAL),
        ]
    )
    view = QTableView()
    view.setModel(model)
    delegate = LogDelegate(gui.kit)
    for wrap in (False, True):
        delegate.wrap = wrap
        for row in range(5):
            for column in Column:
                paint(delegate, view, row, column)
    selected = QStyleOptionViewItem()
    selected.rect = QRect(0, 0, 100, 30)
    selected.state |= QStyle.StateFlag.State_Selected
    selected.widget = view
    image = QImage(100, 30, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    delegate.paint(painter, selected, model.index(2, 0))
    detached = QStyleOptionViewItem()
    detached.rect = QRect(0, 0, 100, 30)
    delegate.paint(painter, detached, model.index(3, 0))
    painter.end()


def test_delegate_foreign_index_falls_back(gui: GuiContext, qapp: object) -> None:
    other = QStandardItemModel(1, 1)
    view = QTableView()
    view.setModel(other)
    delegate = LogDelegate(gui.kit)
    image = QImage(100, 30, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 100, 30)
    delegate.paint(painter, option, other.index(0, 0))
    painter.end()
    assert other.index(0, 0).data(RECORD_ROLE) is None


def test_row_height_and_font(gui: GuiContext, qapp: object) -> None:
    delegate = LogDelegate(gui.kit)
    delegate.message_width = 120
    font = QTableView().font()
    tall = delegate.row_height(record(Level.INFO, "word " * 80), font, 10)
    flat = delegate.row_height(record(Level.INFO, "x"), font, 10)
    assert tall > flat >= 10
    assert mono_font(font, gui.kit).styleHint().name == "Monospace"


@pytest.mark.parametrize("level", list(Level))
def test_tints(gui: GuiContext, level: Level) -> None:
    tint = LogDelegate(gui.kit)._tint(record(level))  # pyright: ignore[reportPrivateUsage]
    assert (tint is not None) == (level >= Level.WARNING)
