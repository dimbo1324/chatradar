# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import TYPE_CHECKING

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest

from chatimport.gui.format import format_count
from chatimport.gui.i18n import plural, tr
from chatimport.gui.pages.search import DEBOUNCE_MS, LOADING, NOTICE, RESULTS
from chatimport.search_types import (
    DEFAULT_PAGE_SIZE,
    ChatChoice,
    IndexState,
    IndexStatus,
    SearchQuery,
)
from chatimport.search_types import (
    SearchPage as Page,
)
from tests.unit.gui.search.conftest import worker_of
from tests.unit.gui.search.fakes import NOW, FakeBackend, make_hit, ready_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from chatimport.gui.pages.search import SearchPage
    from chatimport.search_types import SearchHit
    from tests.unit.gui.conftest import FakeBridge

    type Maker = Callable[..., SearchPage]


def reviews(count: int, *, chat_id: int = 1, title: str = "Chat one") -> list[SearchHit]:
    return [
        make_hit(n, f"review number {n}", chat_id=chat_id, title=title, age_hours=n / 100)
        for n in range(count)
    ]


def search_for(page: SearchPage, text: str) -> None:
    page.field.setText(text)
    page.run_query()


def row(page: SearchPage) -> int:
    return page.results.currentIndex().row()


def test_a_new_page_is_idle(make_page: Maker, backend: FakeBackend) -> None:
    page = make_page()
    assert page.title_key == "nav.search"
    assert tr(page.title_key) == "Search"
    assert tr(page.subtitle_key) == "Find any stored message as you type"
    assert page.stack.currentIndex() == NOTICE
    assert page.notice.accessibleName() == "Search your whole archive"
    assert "Ctrl+F" in page.field.placeholderText()
    assert page.count.text() == ""
    assert page.strip.label.text() == "Checking the index"
    assert page.previous_button.isHidden()
    assert page.next_button.isHidden()
    assert page.context.isHidden()
    assert page.state is None
    assert backend.queries == []
    assert worker_of(page).pending == []


def test_typing_waits_for_the_debounce_then_searches(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = [make_hit(1, "a review of it")]
    page = make_page()
    page.field.setText("rev")
    assert page._debounce.isActive()
    assert page._debounce.interval() == DEBOUNCE_MS == 120
    assert backend.queries == []
    page.run_query()
    assert not page._debounce.isActive()
    assert len(backend.queries) == 1
    query = backend.queries[0]
    assert query.text == "rev"
    assert query.chat_ids is None
    assert query.since is None
    assert query.limit == DEFAULT_PAGE_SIZE
    assert query.offset == 0
    assert page.stack.currentIndex() == RESULTS
    assert page.model.loaded == 1
    assert page.count.text() == "1 result"
    assert page.delegate.needle == "rev"
    assert page.busy.isHidden()
    assert not page.previous_button.isHidden()


def test_a_blank_box_clears_the_list_at_once(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    assert page.model.loaded == 3
    seq = page._seq
    page.field.setText("   ")
    assert page._seq == seq + 1
    assert not page._debounce.isActive()
    assert page.model.loaded == 0
    assert page._query is None
    assert page.stack.currentIndex() == NOTICE
    assert page.notice.accessibleName() == "Search your whole archive"
    assert page.count.text() == ""
    assert page.previous_button.isHidden()


def test_the_counter_uses_plural_forms_and_grouping(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(1200)
    page = make_page()
    search_for(page, "review")
    assert page.count.text() == "1,200 results"
    assert page.count.toolTip() == "100 loaded"
    page.gui.language.set_language("ru")
    search_for(page, "review")
    assert page.count.text() == plural(1200, "find.count", n=format_count(1200, "ru"))


def test_nothing_found(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(2)
    page = make_page()
    search_for(page, "zzz")
    assert page.stack.currentIndex() == NOTICE
    assert page.notice.accessibleName() == "Nothing found"
    assert page.count.text() == "No results"
    assert page.model.total == 0


def test_short_queries_show_a_hint(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(2)
    page = make_page()
    search_for(page, "re")
    assert not page.hint.isHidden()
    assert page.hint.text() == tr("find.state.short.text")
    search_for(page, "rev")
    assert page.hint.isHidden()
    assert page.hint.text() == ""


def test_an_older_answer_never_replaces_a_newer_one(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = [make_hit(1, "alpha beta"), make_hit(2, "alpha")]
    page = make_page(manual=True)
    worker = worker_of(page)
    search_for(page, "alph")
    search_for(page, "alpha b")
    assert len(worker.pending) == 2
    assert not page.busy.isHidden()
    worker.resolve(1)
    assert page.model.loaded == 1
    assert page.model.needle == "alpha b"
    assert page.busy.isHidden()
    worker.resolve(0)
    assert page.model.loaded == 1
    assert page.model.needle == "alpha b"
    assert page.stack.currentIndex() == RESULTS


def test_the_skeleton_shows_only_while_nothing_is_listed(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = reviews(3)
    page = make_page(manual=True)
    worker = worker_of(page)
    search_for(page, "review")
    assert page.stack.currentIndex() == LOADING
    worker.resolve(0)
    assert page.stack.currentIndex() == RESULTS
    search_for(page, "review n")
    assert page.stack.currentIndex() == RESULTS
    assert not page.busy.isHidden()
    worker.resolve(1)
    assert page.busy.isHidden()


def test_a_failing_search_shows_an_error_without_the_query(
    make_page: Maker, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    backend.fail_search = True
    page = make_page()
    with caplog.at_level(logging.WARNING):
        search_for(page, "secretquery")
    assert page.notice.accessibleName() == "The search failed"
    assert page.stack.currentIndex() == NOTICE
    assert page.busy.isHidden()
    assert "RuntimeError" in caplog.text
    assert "scripted failure" not in caplog.text
    assert "secretquery" not in caplog.text


def test_without_an_index_the_page_explains(make_page: Maker, backend: FakeBackend) -> None:
    page = make_page(present=False)
    search_for(page, "abc")
    assert page._no_backend
    assert page.state is IndexState.MISSING
    assert page.notice.accessibleName() == "The search index is not built yet"
    assert page.strip.label.text() == "No search index yet"
    assert page.count.text() == ""
    seq = page._seq
    search_for(page, "abcd")
    assert page._seq == seq + 1
    assert page.busy.isHidden()
    assert page.model.loaded == 0
    assert backend.queries == []


def test_a_disabled_index_blocks_searching(make_page: Maker, backend: FakeBackend) -> None:
    backend.index_status = IndexStatus(IndexState.DISABLED, 0, 0, None)
    page = make_page()
    page.refresh_status()
    assert page.state is IndexState.DISABLED
    assert page.strip.label.text() == "Search is off"
    search_for(page, "abc")
    assert backend.queries == []
    assert page.notice.accessibleName() == "Search is off"
    assert page.stack.currentIndex() == NOTICE


def test_a_missing_index_file_blocks_searching(make_page: Maker, backend: FakeBackend) -> None:
    backend.index_status = IndexStatus(IndexState.MISSING, 0, 0, None)
    page = make_page()
    page.refresh_status()
    search_for(page, "abc")
    assert backend.queries == []
    assert page.notice.accessibleName() == "The search index is not built yet"


def test_a_ready_index_is_summarised_and_its_chats_listed(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.chat_list = (ChatChoice(1, "Alpha", 6),)
    backend.index_status = ready_status(10)
    page = make_page()
    page.refresh_status()
    assert page.state is IndexState.READY
    assert page.strip.label.text() == "10 messages in the index"
    assert page.chat_filter.button.isEnabled()


def test_building_shows_progress_and_polls_while_visible(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.index_status = IndexStatus(IndexState.BUILDING, 47, 100, NOW)
    page = make_page()
    page.show()
    assert page.state is IndexState.BUILDING
    assert page.strip.label.text() == "Indexing 47%"
    assert not page.strip.progress.isHidden()
    assert page._poll.isActive()
    page.hide()
    assert not page._poll.isActive()
    page.show()
    assert page._poll.isActive()
    backend.index_status = ready_status()
    page.refresh_status()
    assert not page._poll.isActive()
    assert page.strip.progress.isHidden()


def test_a_missing_index_is_polled_for_while_visible(make_page: Maker) -> None:
    page = make_page(present=False)
    page.show()
    assert page.state is IndexState.MISSING
    assert page._poll.isActive()


def test_polling_never_starts_on_a_hidden_page(make_page: Maker, backend: FakeBackend) -> None:
    backend.index_status = IndexStatus(IndexState.BUILDING, 1, 10, NOW)
    page = make_page()
    page.refresh_status()
    assert not page._poll.isActive()


def test_finishing_the_index_repeats_the_query(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(2)
    backend.index_status = IndexStatus(IndexState.BUILDING, 1, 10, NOW)
    page = make_page()
    page.refresh_status()
    search_for(page, "review")
    assert len(backend.queries) == 1
    page.refresh_status()
    assert len(backend.queries) == 1
    backend.index_status = ready_status()
    page.refresh_status()
    assert len(backend.queries) == 2
    page.refresh_status()
    assert len(backend.queries) == 2


def test_the_idle_notice_follows_the_index(make_page: Maker, backend: FakeBackend) -> None:
    backend.index_status = IndexStatus(IndexState.BUILDING, 1, 10, NOW)
    page = make_page()
    page.refresh_status()
    assert page.notice.accessibleName() == "Search is still indexing"
    backend.index_status = ready_status()
    page.refresh_status()
    assert page.notice.accessibleName() == "Search your whole archive"


def test_a_failing_status_read_changes_nothing(
    make_page: Maker, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    backend.fail_status = True
    page = make_page()
    with caplog.at_level(logging.WARNING):
        page.refresh_status()
    assert page.state is None
    assert "RuntimeError" in caplog.text


def test_a_changed_snapshot_refreshes_the_status(
    make_page: Maker, backend: FakeBackend, bridge: FakeBridge
) -> None:
    page = make_page()
    assert page.state is None
    bridge.snapshot.emit({"service": "running"})
    assert backend.status_calls == 0
    bridge.snapshot.emit({"search": {"state": "building", "indexed": 1}})
    assert backend.status_calls == 1
    bridge.snapshot.emit({"search": {"state": "building", "indexed": 1}})
    assert backend.status_calls == 1
    bridge.snapshot.emit({"search": {"state": "ready", "indexed": 9}})
    assert backend.status_calls == 2


def test_results_arrive_page_by_page(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(250)
    page = make_page()
    search_for(page, "review")
    assert page.model.loaded == 100
    assert page.model.total == 250
    assert page.count.text() == "250 results"
    assert page.count.toolTip() == "100 loaded"
    assert page.model.canFetchMore()
    page.model.fetchMore()
    assert page.model.loaded == 200
    assert page.count.toolTip() == "200 loaded"
    page.model.fetchMore()
    assert page.model.loaded == 250
    assert page.count.toolTip() == ""
    assert not page.model.canFetchMore()
    assert [q.offset for q in backend.queries] == [0, 100, 200]
    assert {q.text for q in backend.queries} == {"review"}


def test_a_late_extra_page_of_an_older_search_is_dropped(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = reviews(250)
    page = make_page(manual=True)
    worker = worker_of(page)
    search_for(page, "review")
    worker.resolve(0)
    page.model.fetchMore()
    assert len(worker.pending) == 2
    search_for(page, "review n")
    worker.resolve(1)
    assert page.model.loaded == 100
    assert page.model.fetching
    worker.resolve(2)
    assert page.model.loaded == 100
    assert not page.model.fetching


def test_a_failing_extra_page_can_be_retried(
    make_page: Maker, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    backend.hits = reviews(250)
    page = make_page()
    search_for(page, "review")
    backend.fail_search = True
    with caplog.at_level(logging.WARNING):
        page.model.fetchMore()
    assert not page.model.fetching
    assert page.model.loaded == 100
    assert "loading more results failed" in caplog.text
    backend.fail_search = False
    page.model.fetchMore()
    assert page.model.loaded == 200


def test_unusable_extra_pages_are_refused(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(250)
    page = make_page()
    search_for(page, "review")
    done: Future[Page | None] = Future()
    done.set_result(None)
    page._advance_after_fetch = True
    page._on_more_page(page._seq, done)
    assert not page._advance_after_fetch
    other: Future[Page | None] = Future()
    other.set_result(Page(tuple(reviews(2)), 250, SearchQuery(text="other", offset=100)))
    page._on_more_page(page._seq, other)
    assert page.model.loaded == 100
    assert not page.model.fetching


def test_an_extra_page_needs_a_query(make_page: Maker) -> None:
    page = make_page()
    page._fetch_more(0)
    assert not page.model.fetching
    assert worker_of(page).pending == []


def test_extra_pages_need_an_index(make_page: Maker) -> None:
    page = make_page(present=False)
    page._query = SearchQuery(text="x")
    page.model.reset(Page((make_hit(1, "x"),), 5, SearchQuery(text="x")))
    page.model.fetchMore()
    assert not page.model.fetching
    assert page.model.loaded == 1


def test_stepping_through_results(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    assert row(page) == -1
    page.select_next()
    assert row(page) == 0
    selected = page.selected_hit()
    assert selected is not None
    assert selected.msg_id == 0
    page.select_next()
    page.select_next()
    assert row(page) == 2
    page.select_next()
    assert row(page) == 2
    page.select_previous()
    assert row(page) == 1
    page.select_previous()
    page.select_previous()
    assert row(page) == 0


def test_previous_from_nothing_selects_the_last_result(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page.select_previous()
    assert row(page) == 2
    page.results.setCurrentIndex(QModelIndex())
    assert page.selected_hit() is None


def test_keys_and_buttons_step(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(4)
    page = make_page()
    search_for(page, "review")
    QTest.keyClick(page.field, Qt.Key.Key_Return)
    assert row(page) == 0
    QTest.keyClick(page.field, Qt.Key.Key_Down)
    assert row(page) == 1
    QTest.keyClick(page.field, Qt.Key.Key_Up)
    assert row(page) == 0
    QTest.keyClick(page.field, Qt.Key.Key_Return)
    QTest.keyClick(page.field, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert row(page) == 0
    page.next_button.click()
    assert row(page) == 1
    page.previous_button.click()
    assert row(page) == 0


def test_stepping_past_the_loaded_part_fetches_the_next_page(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = reviews(250)
    page = make_page()
    search_for(page, "review")
    page._select_row(99)
    page.select_next()
    assert page.model.loaded == 200
    assert row(page) == 100
    assert not page._advance_after_fetch


def test_a_failed_fetch_does_not_leave_the_page_waiting(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = reviews(250)
    page = make_page()
    search_for(page, "review")
    page._select_row(99)
    backend.fail_search = True
    page.select_next()
    assert row(page) == 99
    assert not page._advance_after_fetch
    assert not page.model.fetching
