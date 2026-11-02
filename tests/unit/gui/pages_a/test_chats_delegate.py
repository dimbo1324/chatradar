from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QEvent, QRect
from PySide6.QtGui import QImage, QPainter, QStandardItemModel
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from chatimport.gui.models.chats_model import ROW_ROLE, Column
from chatimport.gui.pages.chats import ChatsPage
from chatimport.gui.pages.chats_delegate import ChatsDelegate

from .conftest import chat, everything, snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from chatimport.gui.context import GuiContext


@pytest.fixture
def page(gui: GuiContext) -> Iterator[ChatsPage]:
    built = ChatsPage(gui)
    built.resize(1400, 800)
    yield built
    built.close()
    built.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def painted(page: ChatsPage) -> QImage:
    page.show()
    QApplication.processEvents()
    return page.table.viewport().grab().toImage()


def non_blank(image: QImage) -> bool:
    background = image.pixel(0, 0)
    return any(
        image.pixel(x, y) != background
        for x in range(0, image.width(), 7)
        for y in range(0, image.height(), 5)
    )


def test_every_column_and_state_paints(page: ChatsPage) -> None:
    page.set_snapshot(everything())
    image = painted(page)
    assert image.width() > 0
    assert non_blank(image)


def test_animated_progress_phases_paint(page: ChatsPage) -> None:
    page.set_snapshot(
        snapshot(
            [
                chat(1, "Alpha", state="running", progress=0.5),
                chat(2, "Bravo", state="running"),
            ]
        )
    )
    page.delegate.phase = 0.6
    assert non_blank(painted(page))


def test_rows_with_missing_dates_paint(page: ChatsPage) -> None:
    page.set_snapshot(snapshot([chat(1, "Alpha", age=None), chat(2, "", age=None)]))
    assert non_blank(painted(page))


def test_cell_without_a_chat_row_falls_back_to_the_base_painter(page: ChatsPage) -> None:
    model = QStandardItemModel(1, 1)
    model.setData(model.index(0, 0), "plain", 0)
    delegate = ChatsDelegate(page.gui.kit, page.model)
    image = QImage(120, 30, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 120, 30)
    delegate.paint(painter, option, model.index(0, 0))
    painter.end()
    assert delegate._row(model.index(0, 0)) is None
    assert model.index(0, 0).data(ROW_ROLE) is None


def test_painting_without_a_widget_skips_the_style_background(page: ChatsPage) -> None:
    page.set_snapshot(everything())
    delegate = ChatsDelegate(page.gui.kit, page.model)
    image = QImage(400, 60, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    for column in Column:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 60)
        delegate.paint(painter, option, page.model.index(3, column))
    painter.end()
    assert any(image.pixel(x, 30) != 0 for x in range(0, 400, 3))
