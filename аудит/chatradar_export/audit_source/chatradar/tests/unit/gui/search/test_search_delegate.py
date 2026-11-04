from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import QStyleOptionViewItem

from chatimport.gui.format import format_ago, format_exact
from chatimport.gui.models.search_model import SearchResultsModel
from chatimport.gui.models.search_spans import ELLIPSIS
from chatimport.gui.pages.search_delegate import MAX_LINES, SearchDelegate, body_layout, utc_now
from chatimport.gui.pages.search_parts import ResultsView
from chatimport.search_types import SearchHit, SearchPage, SearchQuery
from tests.unit.gui.search.fakes import NOW, make_hit

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit

WHITE = QColor("white")


def build(
    kit: UiKit, hits: list[SearchHit], needle: str = "rev", width: int = 400
) -> tuple[SearchResultsModel, SearchDelegate]:
    model = SearchResultsModel()
    model.reset(SearchPage(tuple(hits), len(hits), SearchQuery(text=needle)))
    delegate = SearchDelegate(kit, clock=lambda: NOW)
    delegate.needle = needle
    delegate.available_width = width
    return model, delegate


def option(width: int = 400, height: int = 120) -> QStyleOptionViewItem:
    item = QStyleOptionViewItem()
    item.rect = QRect(0, 0, width, height)
    item.font = QFont()
    return item


def painted(delegate: SearchDelegate, model: SearchResultsModel, width: int = 400) -> QImage:
    pixmap = QPixmap(width, 120)
    pixmap.fill(WHITE)
    painter = QPainter(pixmap)
    delegate.paint(painter, option(width), model.index(0, 0))
    painter.end()
    return pixmap.toImage()


def colors(image: QImage) -> set[int]:
    return {image.pixel(x, y) for x in range(0, image.width(), 2) for y in range(image.height())}


def test_a_hit_is_painted(kit: UiKit) -> None:
    model, delegate = build(kit, [make_hit(1, "a review of the plan")])
    assert len(colors(painted(delegate, model))) > 2


def test_matches_are_highlighted(kit: UiKit) -> None:
    hits = [make_hit(1, "a review of the plan")]
    model, delegate = build(kit, hits)
    with_match = painted(delegate, model)
    delegate.needle = "zzz"
    assert painted(delegate, model) != with_match


def test_edited_pill_is_painted(kit: UiKit) -> None:
    plain_model, plain = build(kit, [make_hit(1, "a review", edited=False)])
    edited_model, edited = build(kit, [make_hit(1, "a review", edited=True)])
    assert painted(edited, edited_model) != painted(plain, plain_model)


def test_head_stacks_when_it_does_not_fit(kit: UiKit) -> None:
    hit = make_hit(1, "a review", title="A rather long chat title for this row", edited=True)
    _model, delegate = build(kit, [hit])
    font = QFont()
    assert delegate._is_stacked(font, hit, 200)  # pyright: ignore[reportPrivateUsage]
    assert not delegate._is_stacked(font, hit, 2000)  # pyright: ignore[reportPrivateUsage]
    wide = delegate._head_height(font, hit, 2000)  # pyright: ignore[reportPrivateUsage]
    narrow = delegate._head_height(font, hit, 200)  # pyright: ignore[reportPrivateUsage]
    assert narrow > wide


def test_stacked_head_paints(kit: UiKit) -> None:
    hit = make_hit(1, "a review", title="A rather long chat title for this row", edited=True)
    model, delegate = build(kit, [hit], width=220)
    assert len(colors(painted(delegate, model, 220))) > 2


def test_size_hint_follows_the_text(kit: UiKit) -> None:
    short = make_hit(1, "a review")
    long = make_hit(2, "review " + "word " * 80)
    model, delegate = build(kit, [short, long])
    first = delegate.sizeHint(option(), model.index(0, 0))
    second = delegate.sizeHint(option(), model.index(1, 0))
    assert first.width() == 400
    assert second.height() > first.height()


def test_size_hint_reads_the_option_width_without_a_view_width(kit: UiKit) -> None:
    model, delegate = build(kit, [make_hit(1, "a review")], width=0)
    assert delegate.sizeHint(option(333), model.index(0, 0)).width() == 333


def test_other_rows_fall_back_to_the_default_delegate(kit: UiKit) -> None:
    other = QStandardItemModel()
    other.appendRow(QStandardItem("plain"))
    _model, delegate = build(kit, [])
    index = other.index(0, 0)
    assert delegate.sizeHint(option(), index).height() > 0
    pixmap = QPixmap(100, 40)
    pixmap.fill(WHITE)
    painter = QPainter(pixmap)
    delegate.paint(painter, option(100, 40), index)
    painter.end()


def test_meta_text_has_the_exact_moment_and_the_age(kit: UiKit) -> None:
    hit = make_hit(1, age_hours=1.0)
    _model, delegate = build(kit, [hit])
    assert delegate.meta_text(hit) == f"{format_exact(hit.date)} · {format_ago(3600.0, 'en')}"


def test_a_future_date_reads_as_just_now(kit: UiKit) -> None:
    hit = make_hit(1)
    future = SearchHit(hit.chat_id, hit.chat_title, 2, NOW + timedelta(hours=2), "x", False, None)
    _model, delegate = build(kit, [future])
    assert delegate.meta_text(future).endswith(format_ago(0.0, "en"))


def test_utc_now_is_aware() -> None:
    assert utc_now().tzinfo is not None


def test_short_text_fits_without_an_ellipsis() -> None:
    layout, height = body_layout("a short text", ((2, 7),), QFont(), 300, QColor("blue"))
    assert layout.text() == "a short text"
    assert layout.lineCount() == 1
    assert height > 0
    assert len(layout.formats()) == 1


def test_long_text_is_clipped_to_a_few_lines() -> None:
    text = "lorem ipsum dolor sit amet " * 40
    layout, _height = body_layout(
        text, ((2, 7), (len(text) - 6, len(text) - 1)), QFont(), 200, QColor("blue")
    )
    assert layout.lineCount() <= MAX_LINES
    assert layout.text().endswith(ELLIPSIS)
    assert len(layout.text()) < len(text)
    assert len(layout.formats()) == 1


def test_a_view_paints_rows_through_the_style(kit: UiKit) -> None:
    model, delegate = build(
        kit, [make_hit(1, "a review"), make_hit(2, "another review", edited=True)]
    )
    view = ResultsView()
    view.setModel(model)
    view.use_delegate(delegate)
    view.resize(420, 300)
    view.show()
    view.setCurrentIndex(model.index(0, 0))
    image = view.grab().toImage()
    assert len(colors(image)) > 3
