# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from chatimport.gui.i18n import plural
from chatimport.gui.pages.search_filters import ChatFilter, StatusStrip
from chatimport.gui.strings import translate
from chatimport.search_types import ChatChoice, IndexState, IndexStatus
from tests.unit.gui.search.fakes import NOW

if TYPE_CHECKING:
    import pytest

    from chatimport.gui.kit import UiKit

CHATS = (ChatChoice(1, "Alpha", 1200), ChatChoice(2, "Beta", 30), ChatChoice(3, "Gamma", 5))


def make_filter(kit: UiKit) -> tuple[ChatFilter, QWidget, list[bool]]:
    owner = QWidget()
    chat_filter = ChatFilter(kit, owner)
    changes: list[bool] = []
    chat_filter.changed.connect(lambda: changes.append(True))
    return chat_filter, owner, changes


def checkable(chat_filter: ChatFilter) -> list[tuple[str, bool]]:
    return [(a.text(), a.isChecked()) for a in chat_filter.menu.actions() if a.isCheckable()]


def test_without_chats_the_button_is_disabled(kit: UiKit) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    assert not chat_filter.button.isEnabled()
    assert chat_filter.button.text() == "All chats"
    labels = [a.text() for a in chat_filter.menu.actions() if not a.isSeparator()]
    assert labels == ["All chats", "No chats in the index yet"]
    assert chat_filter.selected == frozenset()


def test_menu_lists_every_chat_with_its_size(kit: UiKit) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    assert chat_filter.button.isEnabled()
    assert checkable(chat_filter) == [
        ("All chats", True),
        ("Alpha  (1,200)", False),
        ("Beta  (30)", False),
        ("Gamma  (5)", False),
    ]


def test_choosing_chats_updates_the_selection_and_the_button(kit: UiKit) -> None:
    chat_filter, _owner, changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    actions = [a for a in chat_filter.menu.actions() if a.isCheckable()]
    actions[2].trigger()
    assert chat_filter.selected == frozenset({2})
    assert chat_filter.button.text() == "Beta"
    assert not actions[0].isChecked()
    assert actions[2].isChecked()
    assert changes == [True]
    actions[3].trigger()
    assert chat_filter.selected == frozenset({2, 3})
    assert chat_filter.button.text() == plural(2, "find.chats.some")
    actions[2].trigger()
    assert chat_filter.selected == frozenset({3})
    assert chat_filter.button.text() == "Gamma"
    assert len(changes) == 3


def test_all_chats_clears_the_selection(kit: UiKit) -> None:
    chat_filter, _owner, changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    actions = [a for a in chat_filter.menu.actions() if a.isCheckable()]
    actions[1].trigger()
    actions[0].trigger()
    assert chat_filter.selected == frozenset()
    assert chat_filter.button.text() == "All chats"
    assert actions[0].isChecked()
    assert not actions[1].isChecked()
    assert len(changes) == 2


def test_unchecking_all_chats_keeps_them_all_selected(kit: UiKit) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    everything = next(a for a in chat_filter.menu.actions() if a.isCheckable())
    everything.trigger()
    assert chat_filter.selected == frozenset()
    assert everything.isChecked()


def test_chats_that_vanish_leave_the_selection(kit: UiKit) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    [a for a in chat_filter.menu.actions() if a.isCheckable()][1].trigger()
    chat_filter.set_chats(CHATS[1:])
    assert chat_filter.selected == frozenset()
    assert chat_filter.button.text() == "All chats"


def test_the_same_chats_keep_the_same_menu(kit: UiKit) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    before = list(chat_filter.menu.actions())
    chat_filter.set_chats(CHATS)
    assert list(chat_filter.menu.actions()) == before


def test_language_change_relabels_the_menu(kit: UiKit) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    kit.language.set_language("ru")
    chat_filter.retranslate()
    assert chat_filter.button.text() == translate("ru", "find.chats.all")
    first = next(a for a in chat_filter.menu.actions() if a.isCheckable())
    assert first.text() == translate("ru", "find.chats.menu_all")


def test_the_button_opens_the_menu(kit: UiKit, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_filter, _owner, _changes = make_filter(kit)
    chat_filter.set_chats(CHATS)
    opened: list[object] = []
    monkeypatch.setattr(chat_filter.menu, "popup", lambda point, *_args: opened.append(point))
    chat_filter.button.click()
    assert len(opened) == 1


def strip_text(strip: StatusStrip) -> str:
    return strip.label.text()


def test_strip_for_a_ready_index(kit: UiKit) -> None:
    strip = StatusStrip(kit)
    changing = strip.show_state(IndexState.READY, IndexStatus(IndexState.READY, 1500, 1500, NOW))
    assert not changing
    assert strip_text(strip) == "1,500 messages in the index"
    assert strip.progress.isHidden()
    one = strip.show_state(IndexState.READY, IndexStatus(IndexState.READY, 1, 1, NOW))
    assert not one
    assert strip_text(strip) == "1 message in the index"


def test_strip_while_building(kit: UiKit) -> None:
    strip = StatusStrip(kit)
    changing = strip.show_state(IndexState.BUILDING, IndexStatus(IndexState.BUILDING, 47, 100, NOW))
    assert changing
    assert strip_text(strip) == "Indexing 47%"
    assert not strip.progress.isHidden()
    assert strip.progress.value == 0.47
    assert "47" in strip.label.toolTip()
    assert "100" in strip.label.toolTip()


def test_strip_while_building_an_empty_archive(kit: UiKit) -> None:
    strip = StatusStrip(kit)
    assert strip.show_state(IndexState.BUILDING, IndexStatus(IndexState.BUILDING, 0, 0, None))
    assert strip_text(strip) == "Indexing 0%"
    assert strip.progress.value is None


def test_strip_for_the_other_states(kit: UiKit) -> None:
    strip = StatusStrip(kit)
    disabled = IndexStatus(IndexState.DISABLED, 0, 0, None)
    assert not strip.show_state(IndexState.DISABLED, disabled)
    assert strip_text(strip) == "Search is off"
    assert strip.show_state(IndexState.MISSING, None)
    assert strip_text(strip) == "No search index yet"
    assert not strip.show_state(None, None)
    assert strip_text(strip) == "Checking the index"
    assert not strip.show_state(IndexState.READY, None)
    assert strip_text(strip) == "Checking the index"
    assert strip.label.toolTip() == ""
    assert strip.progress.isHidden()


def test_strip_follows_the_zoom(kit: UiKit) -> None:
    strip = StatusStrip(kit)
    before = strip.progress.maximumWidth()
    kit.zoom.set_factor(1.5)
    assert strip.progress.maximumWidth() > before
