from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QLabel, QWidget

from chatimport.gui.pages.settings_form import FieldRow, SettingsCard, TimeEdit, divider
from chatimport.gui.widgets.button import Button

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from chatimport.gui.kit import UiKit


def test_divider_is_a_frame(qapp: QApplication) -> None:
    assert divider().property("role") == "divider"


def test_field_row_texts_and_hint_visibility(kit: UiKit) -> None:
    editor = QWidget()
    row = FieldRow(kit, editor, label="Name", hint="Hint")
    assert not row._hint.isHidden()
    row.set_texts("Other")
    assert row._hint.isHidden()
    assert row._label.text() == "Other"
    assert editor.accessibleName() == "Other"
    row.set_texts("Other", "Again")
    assert not row._hint.isHidden()


def test_field_row_editor_width_and_resize(kit: UiKit) -> None:
    fixed = FieldRow(kit, QWidget(), editor_width=100)
    assert fixed.editor.width() == kit.px(100)
    free = QWidget()
    flexible = FieldRow(kit, free, editor_width=None)
    assert free.minimumWidth() == 0
    flexible.set_texts("A fairly long label " * 8, "and a long hint " * 8)
    flexible.resize(120, 400)
    flexible.show()
    flexible.resizeEvent(QResizeEvent(QSize(120, 400), QSize(200, 400)))
    assert flexible._label.minimumHeight() > 0
    flexible.resizeEvent(QResizeEvent(QSize(120, 400), QSize(200, 400)))
    flexible.hide()


def test_settings_card_rows_messages_and_status(kit: UiKit) -> None:
    card = SettingsCard(kit, "demo", "info")
    assert card.objectName() == "SettingsCard_demo"
    card.set_texts("Title", "Lede")
    assert not card._lede.isHidden()
    card.set_texts("Title")
    assert card._lede.isHidden()
    first, second = QLabel("one"), QLabel("two")
    card.add_row(first)
    card.add_row(second)
    plain = QLabel("plain")
    card.add_plain(plain)
    index = card.body.indexOf
    assert index(first) < index(second) < index(plain) < index(card.message)
    button = Button(kit)
    card.add_footer_button(button)
    assert card._footer.indexOf(button) >= 0
    card.show_message("danger", "Bad", "Title")
    assert not card.message.isHidden()
    card.clear_message()
    assert card.message.isHidden()
    card.set_status("unsaved")
    assert card._status.text() == "unsaved"
    kit.zoom.set_factor(1.25)


def test_time_edit_roundtrip_and_signal(kit: UiKit) -> None:
    edit = TimeEdit(kit)
    seen: list[None] = []
    edit.changed.connect(lambda: seen.append(None))
    edit.set_text("07:05")
    assert edit.text == "07:05"
    assert seen
    edit.set_text("junk")
    assert edit.text == "00:00"
    edit.setAccessibleName("Daily")
    assert edit._hours.accessibleName() == "Daily (h)"
    assert edit._minutes.accessibleName() == "Daily (min)"
