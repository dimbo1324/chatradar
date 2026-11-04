from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel

from chatimport.gui.format import format_exact
from chatimport.gui.pages.search_context import ContextPanel
from chatimport.gui.strings import translate
from chatimport.search_types import ContextMessage
from tests.unit.gui.search.fakes import NOW, make_hit

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit


def message(
    msg_id: int, text: str, *, target: bool = False, edited: bool = False
) -> ContextMessage:
    return ContextMessage(msg_id, NOW, text, edited, target)


def labels(panel: ContextPanel) -> list[str]:
    return [label.text() for label in panel.findChildren(QLabel)]


def test_a_new_panel_has_no_hit_and_disabled_actions(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    assert panel.hit is None
    assert panel.message_count == 0
    assert not panel.open_button.isEnabled()
    assert not panel.link_button.isEnabled()
    assert not panel.text_button.isEnabled()
    assert panel.note == ""


def test_loading_names_the_chat_and_enables_the_actions(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    hit = make_hit(5, "text", title="Chat one")
    panel.show_loading(hit)
    assert panel.hit == hit
    assert panel.note == "Loading the neighbouring messages"
    assert panel.message_count == 0
    assert panel.open_button.isEnabled()
    assert panel.link_button.isEnabled()
    assert panel.text_button.isEnabled()
    assert panel._subtitle.full_text() == "Chat one"  # pyright: ignore[reportPrivateUsage]


def test_a_hit_without_a_link_cannot_be_opened_or_linked(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    panel.show_loading(make_hit(5, link=None))
    assert not panel.open_button.isEnabled()
    assert not panel.link_button.isEnabled()
    assert panel.text_button.isEnabled()
    assert panel.open_button.toolTip() == "This message has no link"


def test_messages_become_rows_and_the_target_is_marked(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    hit = make_hit(2, "the review text")
    panel.show_messages(
        hit,
        (
            message(1, "before"),
            message(2, "the review text", target=True, edited=True),
            message(3, "<b>after</b>"),
        ),
        "review",
    )
    assert panel.message_count == 3
    assert panel.note == ""
    rows = [row for row, _target in panel._rows]  # pyright: ignore[reportPrivateUsage]
    assert [row.property("target") for row in rows] == [False, True, False]
    texts = labels(panel)
    assert any("Found message" in text and "edited" in text for text in texts)
    assert any(format_exact(NOW) in text for text in texts)
    assert any("background-color" in text and "review" in text for text in texts)
    assert any("&lt;b&gt;after&lt;/b&gt;" in text for text in texts)


def test_only_the_found_message_is_highlighted(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    panel.show_messages(
        make_hit(2),
        (message(1, "review of the plan"), message(2, "review", target=True)),
        "review",
    )
    marked = [text for text in labels(panel) if "background-color" in text]
    assert len(marked) == 1


def test_no_neighbours_leaves_a_note(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    panel.show_messages(make_hit(2), (), "review")
    assert panel.note == "The neighbouring messages are no longer available."
    assert panel.message_count == 0


def test_a_new_load_replaces_the_rows(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    panel.show_messages(make_hit(2), (message(1, "a"), message(2, "b", target=True)), "b")
    panel.show_loading(make_hit(9))
    assert panel.message_count == 0
    assert panel.hit is not None
    assert panel.hit.msg_id == 9


def test_buttons_emit_their_signals(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    panel.show_loading(make_hit(5))
    seen: list[str] = []
    panel.close_requested.connect(lambda: seen.append("close"))
    panel.open_requested.connect(lambda: seen.append("open"))
    panel.copy_link_requested.connect(lambda: seen.append("link"))
    panel.copy_text_requested.connect(lambda: seen.append("text"))
    for button in (panel.close_button, panel.open_button, panel.link_button, panel.text_button):
        button.click()
    assert seen == ["close", "open", "link", "text"]


def test_language_theme_and_zoom_changes_are_followed(kit: UiKit) -> None:
    panel = ContextPanel(kit)
    panel.show_messages(make_hit(2), (message(1, "a"), message(2, "b", target=True)), "b")
    kit.language.set_language("ru")
    assert panel.open_button.text() == translate("ru", "find.ctx.open")
    assert panel.accessibleName() == translate("ru", "find.ctx.title")
    kit.theme.set_preference("dark")
    assert kit.palette.surface in panel.styleSheet()
    kit.zoom.set_factor(1.5)
    assert panel.message_count == 2
