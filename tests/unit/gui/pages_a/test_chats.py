from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtWidgets import QApplication, QMenu

from chatimport.gui.models.chats_model import Column, FilterMode
from chatimport.gui.models.ticker import shared_ticker
from chatimport.gui.pages import chats as chats_module
from chatimport.gui.pages.chats import ChatsPage

from .conftest import chat, everything, snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from chatimport.gui.context import GuiContext
    from chatimport.gui.pages.library_dialog import LibraryDialog
    from tests.unit.gui.conftest import FakeBridge


class RecordingMenu(QMenu):
    opened: list[RecordingMenu] = []  # noqa: RUF012

    def exec(self, *_args: object) -> None:  # type: ignore[override]
        RecordingMenu.opened.append(self)


@pytest.fixture
def opened_menus(page: ChatsPage, monkeypatch: pytest.MonkeyPatch) -> list[RecordingMenu]:
    RecordingMenu.opened = []
    real = page.chat_actions.build_menu

    def build(rows: Any, parent: Any = None) -> QMenu:
        real(rows, parent).deleteLater()
        return RecordingMenu(parent or page)

    monkeypatch.setattr(page.chat_actions, "build_menu", build)
    return RecordingMenu.opened


@pytest.fixture
def page(gui: GuiContext) -> Iterator[ChatsPage]:
    built = ChatsPage(gui)
    built.resize(1300, 700)
    yield built
    built.chat_actions._runner._pool.shutdown(wait=True)
    built.close()
    built.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def populate(page: ChatsPage, raw: dict[str, Any] | None = None) -> None:
    page.set_snapshot(raw or everything())
    QApplication.processEvents()


def shown_ids(page: ChatsPage) -> set[int]:
    proxy = page.proxy
    return {
        page.model.row_at(proxy.mapToSource(proxy.index(i, 0)).row()).chat_id
        for i in range(proxy.rowCount())
    }


def test_empty_library_shows_the_empty_state(page: ChatsPage) -> None:
    assert page.stack.currentWidget() is page.empty
    assert page.selected_rows() == []
    assert not page.pause_button.isEnabled()
    assert not page.more_button.isEnabled()


def test_last_snapshot_fills_the_table_on_construction(gui: GuiContext, bridge: FakeBridge) -> None:
    bridge.last_snapshot = snapshot([chat(1, "Alpha")])
    page = ChatsPage(gui)
    assert page.stack.currentWidget() is page.table
    assert page.model.rowCount() == 1
    assert page.snapshot.chat(1) is not None


def test_snapshot_signal_populates_and_updates_in_place(
    page: ChatsPage, bridge: FakeBridge
) -> None:
    bridge.snapshot.emit(everything())
    assert page.model.rowCount() == 12
    assert page.stack.currentWidget() is page.table
    assert page.count.text()
    bridge.snapshot.emit(snapshot([chat(1, "Alpha", records=99)]))
    assert page.model.rowCount() == 1


def test_animation_follows_running_state(page: ChatsPage) -> None:
    ticker = shared_ticker()
    populate(page)
    assert ticker.animating
    populate(page)
    assert ticker.animating
    populate(page, snapshot([chat(1, state="done")]))
    assert not ticker.animating
    populate(page, snapshot([chat(1, state="done")]))
    assert not ticker.animating


@pytest.mark.parametrize("mode", list(FilterMode))
def test_every_filter_mode_filters(page: ChatsPage, mode: FilterMode) -> None:
    populate(page)
    page.filter.setCurrentIndex(page.filter.findData(mode.value))
    assert page.proxy.mode is mode
    assert page.stack.currentWidget() in (page.table, page.no_matches)
    assert page.count.text()


def test_filter_modes_pick_the_right_rows(page: ChatsPage) -> None:
    populate(page)
    page.filter.setCurrentIndex(page.filter.findData("running"))
    assert shown_ids(page) == {1, 2}
    page.filter.setCurrentIndex(page.filter.findData("waiting"))
    assert shown_ids(page) == {3, 4, 11, 12}
    page.filter.setCurrentIndex(page.filter.findData("paused"))
    assert shown_ids(page) == {6}
    page.filter.setCurrentIndex(page.filter.findData("problems"))
    assert {4, 7, 8, 11} <= shown_ids(page)


def test_search_by_title_and_id_and_no_matches(page: ChatsPage) -> None:
    populate(page)
    page.search.query_changed.emit("alp")
    assert shown_ids(page) == {1}
    page.search.query_changed.emit("10")
    assert 10 in shown_ids(page)
    page.search.query_changed.emit("zzzz")
    assert page.stack.currentWidget() is page.no_matches
    assert "/" in page.count.text()
    page.search.query_changed.emit("")
    assert page.stack.currentWidget() is page.table


def test_unknown_filter_position_is_ignored(page: ChatsPage) -> None:
    populate(page)
    page._on_filter(-1)
    assert page.proxy.mode is FilterMode.ALL


def test_selection_drives_the_action_buttons(page: ChatsPage) -> None:
    populate(page)
    page.table.selectRow(0)
    assert len(page.selected_rows()) == 1
    assert page.recheck_button.isEnabled()
    assert page.more_button.isEnabled()
    page.table.clearSelection()
    assert not page.deeper_button.isEnabled()
    page.table.selectAll()
    assert len(page.selected_rows()) == 12
    assert page.pause_button.isEnabled()
    assert page.resume_button.isEnabled()


def test_selecting_only_paused_rows_disables_pause(page: ChatsPage) -> None:
    populate(page)
    page.search.query_changed.emit("foxtrot")
    page.table.selectRow(0)
    assert not page.pause_button.isEnabled()
    assert page.resume_button.isEnabled()
    page.search.query_changed.emit("alpha")
    page.table.selectRow(0)
    assert page.pause_button.isEnabled()
    assert not page.resume_button.isEnabled()


def test_toolbar_buttons_call_the_actions(
    page: ChatsPage, bridge: FakeBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    populate(page, snapshot([chat(1, "Alpha"), chat(2, "Bravo", paused=True)]))
    sent: list[str] = []

    def fake_send(command: str, rows: object, extra: object = None) -> None:
        sent.append(command)

    monkeypatch.setattr(page.chat_actions, "_send", fake_send)
    page.table.selectAll()
    page.pause_button.click()
    page.resume_button.click()
    page.recheck_button.click()
    page.deeper_button.click()
    assert sent == ["pause", "resume", "recheck", "deeper"]


def test_clicking_last_message_toggles_absolute_time(page: ChatsPage) -> None:
    populate(page)
    assert not page.model.absolute_time
    page._on_clicked(page.proxy.index(0, Column.CHAT))
    assert not page.model.absolute_time
    page._on_clicked(page.proxy.index(0, Column.LAST_MESSAGE))
    assert page.model.absolute_time
    assert page.gui.settings.settings.chats_absolute_time is True
    page._on_clicked(page.proxy.index(0, Column.LAST_MESSAGE))
    assert not page.model.absolute_time


def test_context_menu_selects_the_row_and_opens(
    page: ChatsPage, opened_menus: list[RecordingMenu]
) -> None:
    opened = opened_menus
    populate(page)
    page.show()
    QApplication.processEvents()
    page._on_context_menu(QPoint(-5, -5))
    assert opened == []
    point = page.table.visualRect(page.proxy.index(1, 0)).center()
    page._on_context_menu(point)
    assert len(opened) == 1
    assert len(page.selected_rows()) == 1
    page._on_context_menu(point)
    assert len(opened) == 2
    assert len(page.selected_rows()) == 1


def test_more_menu_opens(page: ChatsPage, opened_menus: list[RecordingMenu]) -> None:
    page._show_more_menu()
    assert len(opened_menus) == 1


def test_library_buttons_open_the_dialog(page: ChatsPage, monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[Any] = []

    def fake_exec(self: LibraryDialog) -> int:
        runs.append(self._errors)
        return 0

    monkeypatch.setattr(chats_module.LibraryDialog, "exec", fake_exec)
    populate(page, snapshot([chat(1)], errors=[{"source": "resolve:@x", "message": "m"}]))
    page.library.click()
    page.library_action.click()
    assert len(runs) == 2
    assert runs[0][0].source == "resolve:@x"


def test_focus_search(page: ChatsPage) -> None:
    page.show()
    page.focus_search()
    QApplication.processEvents()
    assert page.search.hasFocus()


def test_ticker_signals_update_the_page(page: ChatsPage) -> None:
    populate(page)
    ticker = shared_ticker()
    ticker.second.emit()
    ticker.frame.emit(0.25)
    assert page.delegate.phase == 0.25
    page.filter.setCurrentIndex(page.filter.findData("silent_1h"))
    ticker.second.emit()


def test_language_and_theme_changes_rebuild_text_and_legend(
    page: ChatsPage, gui: GuiContext
) -> None:
    populate(page)
    page.filter.setCurrentIndex(page.filter.findData("paused"))
    english = page.library.text()
    gui.language.set_language("ru")
    assert page.library.text() != english
    assert page.proxy.mode is FilterMode.PAUSED
    assert page.filter.currentData() == "paused"
    gui.language.set_language("en")
    gui.theme.set_preference("dark")
    gui.zoom.zoom_in()
    assert page.legend.count() >= 5
