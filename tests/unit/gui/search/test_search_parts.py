from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest

from chatimport.gui.pages.search_delegate import SearchDelegate
from chatimport.gui.pages.search_parts import QueryField, ResultsView, Skeleton, StickyMenu
from chatimport.gui.strings import translate

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit


def release() -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(2, 2),
        QPointF(2, 2),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_query_field_navigation_keys(kit: UiKit) -> None:
    field = QueryField(kit)
    nxt: list[bool] = []
    prev: list[bool] = []
    field.next_requested.connect(lambda: nxt.append(True))
    field.previous_requested.connect(lambda: prev.append(True))
    QTest.keyClick(field, Qt.Key.Key_Return)
    QTest.keyClick(field, Qt.Key.Key_Enter)
    QTest.keyClick(field, Qt.Key.Key_Down)
    assert len(nxt) == 3
    QTest.keyClick(field, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClick(field, Qt.Key.Key_Up)
    assert len(prev) == 2
    assert len(nxt) == 3


def test_query_field_still_types_and_clears(kit: UiKit) -> None:
    field = QueryField(kit)
    QTest.keyClicks(field, "abc")
    assert field.text() == "abc"
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert field.text() == ""


def test_query_field_placeholder_shows_the_shortcut_and_follows_the_language(kit: UiKit) -> None:
    field = QueryField(kit)
    assert "Ctrl+F" in field.placeholderText()
    assert field.accessibleName() == field.placeholderText()
    kit.language.set_language("ru")
    assert field.placeholderText() == translate("ru", "find.placeholder")
    assert "Ctrl+F" in field.placeholderText()


def test_sticky_menu_toggles_without_closing() -> None:
    menu = StickyMenu()
    action = menu.addAction("chat")
    action.setCheckable(True)
    menu.show()
    menu.setActiveAction(action)
    menu.mouseReleaseEvent(release())
    assert action.isChecked()
    assert menu.isVisible()
    menu.mouseReleaseEvent(release())
    assert not action.isChecked()
    assert menu.isVisible()


def test_sticky_menu_leaves_other_entries_to_qt() -> None:
    menu = StickyMenu()
    disabled = menu.addAction("disabled")
    disabled.setCheckable(True)
    disabled.setEnabled(False)
    menu.show()
    menu.setActiveAction(disabled)
    menu.mouseReleaseEvent(release())
    assert not disabled.isChecked()
    menu.setActiveAction(None)  # pyright: ignore[reportArgumentType]
    menu.mouseReleaseEvent(release())
    assert not disabled.isChecked()


def test_skeleton_paints_rows(kit: UiKit) -> None:
    skeleton = Skeleton(kit)
    assert skeleton.sizeHint().width() > 0
    skeleton.resize(300, 400)
    image = QImage(300, 400, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    skeleton.render(image)
    assert image.pixelColor(60, 30) != image.pixelColor(290, 390)


def test_skeleton_stops_at_the_bottom_edge(kit: UiKit) -> None:
    skeleton = Skeleton(kit)
    skeleton.resize(300, 40)
    image = QImage(300, 40, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    skeleton.render(image)
    assert image.height() == 40


def test_results_view_tells_the_delegate_its_width(kit: UiKit) -> None:
    view = ResultsView()
    delegate = SearchDelegate(kit)
    view.use_delegate(delegate)
    view.show()
    view.resize(360, 200)
    assert delegate.available_width == view.viewport().width()
    view.sync_width()
    assert delegate.available_width == view.viewport().width()


def test_results_view_without_a_delegate_still_resizes() -> None:
    view = ResultsView()
    view.resize(300, 200)
    view.sync_width()
    assert view.itemDelegate() is not None
