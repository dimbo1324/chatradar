# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QModelIndex, Qt

from chatimport.gui.format import format_exact
from chatimport.gui.models.search_model import HIT_ROLE, SearchResultsModel, same_search
from chatimport.search_types import SearchPage, SearchQuery
from tests.unit.gui.search.fakes import make_hit


def page_of(
    first: int, count: int, total: int, *, text: str = "abc", offset: int = 0
) -> SearchPage:
    hits = tuple(make_hit(first + n) for n in range(count))
    return SearchPage(hits, total, SearchQuery(text=text, offset=offset))


def test_new_model_is_empty() -> None:
    model = SearchResultsModel()
    assert model.rowCount() == 0
    assert model.total == 0
    assert model.loaded == 0
    assert not model.fetching
    assert model.needle == ""
    assert not model.canFetchMore()
    assert model.hit_at(0) is None
    assert model.hit_at(-1) is None


def test_reset_takes_the_first_page_and_the_real_total() -> None:
    model = SearchResultsModel()
    resets: list[bool] = []
    model.modelReset.connect(lambda: resets.append(True))
    model.reset(page_of(1, 3, 250))
    assert resets == [True]
    assert model.rowCount() == 3
    assert model.total == 250
    assert model.loaded == 3
    assert model.needle == "abc"
    assert model.canFetchMore()


def test_data_roles() -> None:
    model = SearchResultsModel()
    hit = make_hit(1, "some text")
    model.reset(SearchPage((hit,), 1, SearchQuery(text="some")))
    index = model.index(0, 0)
    assert index.data(HIT_ROLE) == hit
    assert index.data(Qt.ItemDataRole.DisplayRole) == "some text"
    assert index.data(Qt.ItemDataRole.ToolTipRole) == format_exact(hit.date)
    assert index.data(Qt.ItemDataRole.DecorationRole) is None
    assert model.data(QModelIndex(), HIT_ROLE) is None
    assert model.data(model.index(5, 0), HIT_ROLE) is None


def test_children_of_a_row_do_not_exist() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 2))
    parent = model.index(0, 0)
    assert model.rowCount(parent) == 0
    assert not model.canFetchMore(parent)
    model.fetchMore(parent)
    assert not model.fetching


def test_fetch_more_asks_for_the_next_offset_once() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 100, 250))
    asked: list[int] = []
    model.more_requested.connect(asked.append)
    model.fetchMore()
    assert asked == [100]
    assert model.fetching
    assert not model.canFetchMore()
    model.fetchMore()
    assert asked == [100]


def test_fetch_more_does_nothing_when_everything_is_loaded() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 3, 3))
    asked: list[int] = []
    model.more_requested.connect(asked.append)
    model.fetchMore()
    assert asked == []


def test_append_continues_the_list() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 100, 250))
    inserted: list[tuple[int, int]] = []
    model.rowsInserted.connect(lambda _parent, first, last: inserted.append((first, last)))
    model.fetchMore()
    assert model.append(page_of(101, 100, 250, offset=100))
    assert inserted == [(100, 199)]
    assert model.loaded == 200
    assert not model.fetching
    assert model.canFetchMore()
    assert model.hit_at(150) is not None


def test_append_raises_the_total_when_the_index_grew() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 2))
    assert model.append(page_of(3, 2, 7, offset=2))
    assert model.total == 7
    assert model.loaded == 4


def test_append_of_an_empty_page_settles_the_total() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 5))
    model.fetchMore()
    assert model.append(page_of(3, 0, 5, offset=2))
    assert model.total == 2
    assert not model.canFetchMore()
    assert not model.fetching


def test_append_refuses_a_page_of_another_search() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 9, text="abc"))
    assert not model.append(page_of(3, 2, 9, text="abd", offset=2))
    assert model.loaded == 2


def test_append_refuses_a_page_with_the_wrong_offset() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 9))
    assert not model.append(page_of(5, 2, 9, offset=4))
    assert not model.append(page_of(1, 2, 9, offset=0))
    assert model.loaded == 2


def test_append_without_a_first_page_is_refused() -> None:
    model = SearchResultsModel()
    assert not model.append(page_of(1, 2, 2, offset=0))


def test_fetch_failed_allows_another_attempt() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 9))
    model.fetchMore()
    model.fetch_failed()
    assert not model.fetching
    assert model.canFetchMore()


def test_clear_empties_everything() -> None:
    model = SearchResultsModel()
    model.reset(page_of(1, 2, 9))
    model.fetchMore()
    model.clear()
    assert model.rowCount() == 0
    assert model.total == 0
    assert model.needle == ""
    assert not model.fetching


def test_same_search_ignores_only_the_offset() -> None:
    base = SearchQuery(text="a", limit=10)
    assert same_search(base, replace(base, offset=30))
    assert not same_search(base, replace(base, text="b"))
    assert not same_search(base, replace(base, limit=20))
    assert not same_search(base, replace(base, chat_ids=frozenset({1})))
