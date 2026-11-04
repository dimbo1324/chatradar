# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTableView, QWidget

from chatimport.gui.widgets.base import set_property, set_role
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.card import Card, PageHeader
from chatimport.gui.widgets.chip import Chip, Dot
from chatimport.gui.widgets.empty_state import EmptyState
from chatimport.gui.widgets.labels import ElidedLabel, make_label
from chatimport.gui.widgets.search_field import SearchField
from chatimport.gui.widgets.stat_card import StatCard
from chatimport.gui.widgets.table import configure_table

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit


def test_set_property_and_role(qapp: QApplication) -> None:
    widget = QWidget()
    set_property(widget, "kind", "a")
    set_property(widget, "kind", "a")
    set_role(widget, "muted")
    assert widget.property("kind") == "a"
    assert widget.property("role") == "muted"


def test_button_variants_and_icon(kit: UiKit) -> None:
    plain = Button(kit, "Go")
    assert plain.variant == "secondary"
    assert plain.icon().isNull()
    primary = Button(kit, "Go", variant="primary", icon_name="check")
    assert not primary.icon().isNull()
    primary.set_variant("danger")
    assert primary.variant == "danger"
    primary.set_icon_name(None)
    secondary = Button(kit, "Go", icon_name="check")
    secondary.set_icon_name("x")
    kit.zoom.zoom_in()
    assert secondary.height() == kit.px(36) or secondary.height() > 0


def test_icon_button_is_square_and_named(kit: UiKit) -> None:
    button = IconButton(kit, "x", "Close")
    assert button.toolTip() == "Close"
    assert button.accessibleName() == "Close"
    assert button.width() == button.height()
    button.set_tooltip("Other")
    assert button.toolTip() == "Other"


def test_callout_title_tone_and_action(kit: UiKit, qapp: QApplication) -> None:
    action = QPushButton("act")
    callout = Callout(kit, "info", "Body", title="Title", action=action)
    assert callout.accessibleName() == "Title"
    callout.set_tone("danger")
    callout.set_body("New")
    callout.set_title("")
    assert callout.property("tone") == "danger"
    bare = Callout(kit, "success", "Only body")
    assert bare.accessibleName() == "Only body"
    kit.theme.set_preference("dark")


def test_card_and_page_header(kit: UiKit) -> None:
    card = Card(kit)
    kit.zoom.zoom_in()
    assert card.body.contentsMargins().left() > 0
    from PySide6.QtWidgets import QHBoxLayout

    trailing = QHBoxLayout()
    header = PageHeader(kit, "Title", "Lede", trailing=trailing)
    header.set_texts("Other")
    header.set_texts("Other", "Lede2")
    bare = PageHeader(kit, "T")
    assert bare is not None


def test_dot_and_chip(kit: UiKit, qapp: QApplication) -> None:
    dot = Dot(kit)
    dot.set_tone("danger")
    dot.resize(dot.size())
    dot.grab()
    kit.theme.set_preference("dark")
    kit.zoom.zoom_in()
    chip = Chip(kit, "Live", "live", icon_name="check", dot=True)
    assert chip.text == "Live"
    chip.set_text("Off")
    chip.set_tone("danger")
    chip.set_dot(False)
    chip.set_icon(None)
    chip.set_icon("x")
    plain = Chip(kit)
    assert plain.text == ""


def test_empty_state(kit: UiKit) -> None:
    state = EmptyState(kit, "info", "Title", "Text", action=QPushButton("a"))
    state.set_icon("x")
    state.set_texts("T2")
    state.set_texts("T3", "Body")
    assert state.accessibleName() == "T3"
    assert EmptyState(kit, "info", "T").accessibleName() == "T"


def test_make_label(qapp: QApplication) -> None:
    label = make_label("x", "muted", wrap=True, selectable=True)
    assert label.wordWrap()
    assert make_label().text() == ""


def test_elided_label(qapp: QApplication) -> None:
    label = ElidedLabel("a very long text that cannot fit anywhere", "muted")
    assert label.full_text().startswith("a very")
    assert label.sizeHint().width() > 0
    assert label.minimumSizeHint().width() == 0
    label.resize(30, 20)
    label.show()
    qapp.processEvents()
    assert label.text() != label.full_text()
    assert label.toolTip() == label.full_text()
    label.setToolTip("custom")
    label.resize(400, 20)
    qapp.processEvents()
    assert label.toolTip() == "custom"
    label.setToolTip("")
    label.resize(500, 20)
    qapp.processEvents()
    assert label.toolTip() == ""
    label.setText("short")
    label.setFont(label.font())
    label.changeEvent(QEvent(QEvent.Type.StyleChange))
    label.changeEvent(QEvent(QEvent.Type.EnabledChange))
    label.close()


def test_search_field_debounce_clear_escape(kit: UiKit, qapp: QApplication) -> None:
    field = SearchField(kit)
    seen: list[str] = []
    field.query_changed.connect(seen.append)
    field.setText("abc")
    field._timer.timeout.emit()
    assert seen == ["abc"]
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert field.text() == ""
    QTest.keyClick(field, Qt.Key.Key_Escape)
    field._clear.trigger()
    QTest.keyClick(field, Qt.Key.Key_A)
    assert field.text() == "a"
    kit.language.set_language("ru")
    kit.theme.set_preference("dark")
    assert field.placeholderText()


def test_stat_card(kit: UiKit) -> None:
    card = StatCard(kit, "Label", "5", hint="hint", icon_name="info", tone="success")
    assert card.accessibleName() == "Label: 5"
    card.set_label("L2")
    card.set_value("7")
    card.set_hint("")
    card.set_hint("h")
    card.set_tone("neutral")
    card.set_tone("danger")
    assert card.accessibleName() == "L2: 7"
    bare = StatCard(kit, "L")
    bare.set_tone("warning")


def test_configure_table(kit: UiKit, qapp: QApplication) -> None:
    view = QTableView()
    configure_table(view, kit)
    before = view.verticalHeader().defaultSectionSize()
    kit.zoom.zoom_in()
    assert view.verticalHeader().defaultSectionSize() >= before
