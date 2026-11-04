# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import logging
from datetime import UTC, timedelta
from typing import TYPE_CHECKING

import shiboken6
from PySide6.QtCore import QModelIndex, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QShortcut
from PySide6.QtTest import QTest

from chatimport.gui.pages import search_actions
from chatimport.gui.pages.search import PAGE_PADDING, PERIODS, SearchPage
from chatimport.gui.pages.search_worker import SearchWorker
from chatimport.gui.strings import translate, translate_plural
from chatimport.search_types import ChatChoice, IndexState, SearchQuery
from chatimport.search_types import SearchPage as Page
from tests.unit.gui.search.conftest import worker_of
from tests.unit.gui.search.fakes import NOW, FakeBackend, make_hit, ready_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from chatimport.search_types import SearchHit

    type Maker = Callable[..., SearchPage]


class FakeDesktop:
    urls: list[str] = []  # noqa: RUF012
    accept = True

    @staticmethod
    def openUrl(url: QUrl) -> bool:
        FakeDesktop.urls.append(url.toString())
        return FakeDesktop.accept


def reviews(count: int, *, link: str | None = "https://t.me/c/1/1") -> list[SearchHit]:
    return [make_hit(n, f"review number {n}", age_hours=n / 100, link=link) for n in range(count)]


def search_for(page: SearchPage, text: str) -> None:
    page.field.setText(text)
    page.run_query()


def opened(make_page: Maker, backend: FakeBackend, count: int = 5) -> SearchPage:
    backend.hits = reviews(count)
    page = make_page()
    search_for(page, "review")
    page._select_row(1)
    page.open_context()
    return page


def test_opening_the_context_loads_the_neighbours(make_page: Maker, backend: FakeBackend) -> None:
    page = opened(make_page, backend)
    hit = page.selected_hit()
    assert hit is not None
    assert not page.context.isHidden()
    assert backend.context_calls == [(hit.chat_id, hit.msg_id, 3, 3)]
    assert page.context.hit == hit
    assert page.context.message_count == 5
    assert page.context.note == ""


def test_enter_and_double_click_open_it_once(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page._select_row(0)
    index = page.model.index(0, 0)
    page.results.activated.emit(index)
    assert len(backend.context_calls) == 1
    page.results.doubleClicked.emit(index)
    assert len(backend.context_calls) == 1
    page.results.activated.emit(QModelIndex())
    assert len(backend.context_calls) == 1


def test_selecting_another_result_reloads_the_context(
    make_page: Maker, backend: FakeBackend
) -> None:
    page = opened(make_page, backend)
    page._select_row(2)
    assert len(backend.context_calls) == 2
    assert page.context.hit == page.selected_hit()


def test_selecting_does_not_open_the_context_by_itself(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page._select_row(1)
    assert page.context.isHidden()
    assert backend.context_calls == []


def test_opening_without_a_selection_does_nothing(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page.open_context()
    assert page.context.isHidden()


def test_closing_and_reopening(make_page: Maker, backend: FakeBackend) -> None:
    page = opened(make_page, backend)
    page.context.close_button.click()
    assert page.context.isHidden()
    assert not page.ctx.is_open
    page.open_context()
    assert not page.context.isHidden()
    assert len(backend.context_calls) == 2


def test_escape_closes_the_context_only_while_it_is_open(
    make_page: Maker, backend: FakeBackend
) -> None:
    page = opened(make_page, backend)
    QTest.keyClick(page, Qt.Key.Key_Escape)
    assert page.context.isHidden()
    QTest.keyClick(page, Qt.Key.Key_Escape)
    QTest.keyClick(page, Qt.Key.Key_A)
    assert page.context.isHidden()


def test_a_late_context_answer_is_dropped(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(5)
    page = make_page(manual=True)
    worker = worker_of(page)
    search_for(page, "review")
    worker.resolve(0)
    page._select_row(0)
    page.open_context()
    page._select_row(1)
    second = page.selected_hit()
    assert len(worker.pending) == 3
    worker.resolve(2)
    assert page.context.hit == second
    assert page.context.message_count == 5
    worker.resolve(1)
    assert page.context.hit == second
    assert page.context.message_count == 5


def test_closing_drops_a_pending_context(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page(manual=True)
    worker = worker_of(page)
    search_for(page, "review")
    worker.resolve(0)
    page._select_row(0)
    page.open_context()
    page.close_context()
    worker.resolve(1)
    assert page.context.message_count == 0


def test_a_failing_context_read_leaves_a_note(
    make_page: Maker, backend: FakeBackend, caplog: pytest.LogCaptureFixture
) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page._select_row(0)
    backend.fail_context = True
    with caplog.at_level(logging.WARNING):
        page.open_context()
    assert page.context.note == "The neighbouring messages are no longer available."
    assert "loading the context failed" in caplog.text
    assert "scripted failure" not in caplog.text


def test_the_context_needs_an_index(make_page: Maker) -> None:
    page = make_page(present=False)
    page.model.reset(Page((make_hit(1, "x"),), 1, SearchQuery(text="x")))
    page._select_row(0)
    page.open_context()
    assert page.context.note == "The neighbouring messages are no longer available."


class Notes:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def __call__(self, _widget: object, tone: str, message: str) -> None:
        self.items.append((tone, message))


def patched(monkeypatch: pytest.MonkeyPatch, *, accept: bool = True) -> Notes:
    notes = Notes()
    monkeypatch.setattr(search_actions, "notify", notes)
    monkeypatch.setattr(search_actions, "QDesktopServices", FakeDesktop)
    FakeDesktop.urls = []
    FakeDesktop.accept = accept
    QGuiApplication.clipboard().setText("")
    return notes


def test_copy_text_and_link(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = patched(monkeypatch)
    page = opened(make_page, backend)
    hit = page.selected_hit()
    assert hit is not None
    page.copy_text()
    assert QGuiApplication.clipboard().text() == hit.text
    page.copy_link()
    assert QGuiApplication.clipboard().text() == "https://t.me/c/1/1"
    assert notes.items == [
        ("success", "The message text is copied."),
        ("success", "The link is copied."),
    ]


def test_the_copy_shortcut_copies_the_selected_message(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    patched(monkeypatch)
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page._select_row(2)
    hit = page.selected_hit()
    assert hit is not None
    shortcuts = page.results.findChildren(QShortcut)
    assert len(shortcuts) == 1
    shortcuts[0].activated.emit()
    assert QGuiApplication.clipboard().text() == hit.text


def test_open_in_telegram(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = patched(monkeypatch)
    page = opened(make_page, backend)
    page.open_in_telegram()
    assert FakeDesktop.urls == ["https://t.me/c/1/1"]
    assert notes.items == []


def test_a_link_that_does_not_open_is_reported(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = patched(monkeypatch, accept=False)
    page = opened(make_page, backend)
    page.open_in_telegram()
    assert notes.items == [("danger", "Could not open the link.")]


def test_a_message_without_a_link_only_copies_its_text(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = patched(monkeypatch)
    backend.hits = reviews(3, link=None)
    page = make_page()
    search_for(page, "review")
    page._select_row(0)
    page.copy_link()
    page.open_in_telegram()
    assert FakeDesktop.urls == []
    assert QGuiApplication.clipboard().text() == ""
    assert notes.items == []
    page.copy_text()
    assert notes.items == [("success", "The message text is copied.")]


def test_actions_without_a_selection_do_nothing(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = patched(monkeypatch)
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page.copy_text()
    page.copy_link()
    page.open_in_telegram()
    assert notes.items == []
    assert FakeDesktop.urls == []
    assert QGuiApplication.clipboard().text() == ""


def test_the_context_buttons_act_on_the_opened_result(
    make_page: Maker, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = patched(monkeypatch)
    page = opened(make_page, backend)
    hit = page.context.hit
    assert hit is not None
    page.context.open_button.click()
    assert FakeDesktop.urls == ["https://t.me/c/1/1"]
    page.context.link_button.click()
    assert QGuiApplication.clipboard().text() == "https://t.me/c/1/1"
    page.context.text_button.click()
    assert QGuiApplication.clipboard().text() == hit.text
    assert [tone for tone, _ in notes.items] == ["success", "success"]


def test_choosing_chats_narrows_the_search(make_page: Maker, backend: FakeBackend) -> None:
    backend.chat_list = (ChatChoice(1, "Alpha", 3), ChatChoice(2, "Beta", 2))
    backend.hits = [
        make_hit(1, "review one", chat_id=1, title="Alpha"),
        make_hit(2, "review two", chat_id=2, title="Beta"),
        make_hit(3, "review three", chat_id=2, title="Beta"),
    ]
    page = make_page()
    page.refresh_status()
    search_for(page, "review")
    assert backend.queries[-1].chat_ids is None
    assert page.model.total == 3
    beta = [a for a in page.chat_filter.menu.actions() if a.isCheckable()][2]
    beta.trigger()
    assert page._debounce.isActive()
    page.run_query()
    assert backend.queries[-1].chat_ids == frozenset({2})
    assert page.model.total == 2


def test_changing_a_filter_without_text_searches_nothing(
    make_page: Maker, backend: FakeBackend
) -> None:
    backend.chat_list = (ChatChoice(1, "Alpha", 3),)
    page = make_page()
    page.refresh_status()
    [a for a in page.chat_filter.menu.actions() if a.isCheckable()][1].trigger()
    page.period.choose(2)
    assert not page._debounce.isActive()
    assert backend.queries == []


def test_the_period_becomes_a_lower_bound(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page()
    assert PERIODS == ("any", "today", "week", "month", "year")
    assert page.since is None
    search_for(page, "review")
    expected = {2: timedelta(days=7), 3: timedelta(days=30), 4: timedelta(days=365)}
    for index, delta in expected.items():
        page.period.choose(index)
        assert page._debounce.isActive()
        page.run_query()
        assert backend.queries[-1].since == NOW - delta
    page.period.choose(0)
    page.run_query()
    assert backend.queries[-1].since is None


def test_today_starts_at_local_midnight(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    page = make_page()
    search_for(page, "review")
    page.period.choose(1)
    page.run_query()
    since = backend.queries[-1].since
    assert since is not None
    assert since.utcoffset() == timedelta(0)
    assert since.tzinfo is UTC
    local = since.astimezone()
    assert (local.hour, local.minute, local.second) == (0, 0, 0)
    assert timedelta(0) <= NOW - since < timedelta(days=2)


def test_focus_search_selects_the_text(make_page: Maker) -> None:
    page = make_page()
    page.field.setText("abc")
    page.focus_search()
    assert page.field.selectedText() == "abc"


def test_a_language_switch_translates_everything(make_page: Maker, backend: FakeBackend) -> None:
    backend.hits = reviews(3)
    backend.chat_list = (ChatChoice(1, "Alpha", 3),)
    backend.index_status = ready_status(10)
    page = make_page()
    page.refresh_status()
    search_for(page, "review")
    page.period.choose(2)
    page.gui.language.set_language("ru")
    assert page.field.placeholderText() == translate("ru", "find.placeholder")
    assert page.count.text() == translate_plural("ru", 3, "find.count", n="3")
    assert page.strip.label.text() == translate_plural("ru", 10, "find.status.ready", n="10")
    assert page.chat_filter.button.text() == translate("ru", "find.chats.all")
    assert page.period.value == "week"
    page.field.clear()
    assert page.notice.accessibleName() == translate("ru", "find.state.idle.title")
    assert page.previous_button.toolTip() == translate("ru", "find.previous")


def test_zoom_and_theme_changes_are_followed(make_page: Maker, kit: UiKit) -> None:
    page = make_page()
    kit.zoom.set_factor(1.5)
    assert page._column.contentsMargins().left() == kit.px(PAGE_PADDING)
    kit.theme.set_preference("dark")
    assert page._column.contentsMargins().left() == kit.px(PAGE_PADDING)


def test_state_property_and_default_period(make_page: Maker, backend: FakeBackend) -> None:
    backend.index_status = ready_status()
    page = make_page()
    assert page.state is None
    page.refresh_status()
    assert page.state is IndexState.READY
    assert page.period.value == "any"


def test_deleting_the_page_closes_its_worker(make_page: Maker) -> None:
    page = make_page()
    worker = worker_of(page)
    assert not worker.closed
    shiboken6.delete(page)
    assert worker.closed


def test_the_real_worker_is_used_by_default(gui: GuiContext) -> None:
    page = SearchPage(gui)
    worker = page._worker
    assert isinstance(worker, SearchWorker)
    worker.close()
    worker._pool.shutdown(wait=True)
    assert worker._closed
