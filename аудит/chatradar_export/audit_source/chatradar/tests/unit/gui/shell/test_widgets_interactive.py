# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.nav_item import NavItem
from chatimport.gui.widgets.progress import BusyStripe, ProgressBar
from chatimport.gui.widgets.segmented import Segmented, SegmentOption
from chatimport.gui.widgets.sidebar import COLLAPSE_KEY, NavEntry, NavSection, Sidebar
from chatimport.gui.widgets.status_bar import StatusBar
from chatimport.gui.widgets.switch import Switch, SwitchRow
from chatimport.gui.widgets.toast import MAX_VISIBLE, Toast, ToastHost
from chatimport.gui.widgets.top_bar import LanguageSwitcher, ThemeSwitcher, TopBar

if TYPE_CHECKING:
    from chatimport.gui.kit import UiKit


def _enter(widget: QWidget) -> None:
    point = QPointF(1, 1)
    widget.enterEvent(QEnterEvent(point, point, point))


def test_bind_kit_without_handlers(kit: UiKit) -> None:
    bind_kit(kit)


class _Owner:
    def __init__(self) -> None:
        self.steps: list[int] = []

    def focus_neighbour(self, item: NavItem, step: int) -> None:
        self.steps.append(step)


def test_nav_item_paint_states(kit: UiKit, qapp: QApplication) -> None:
    item = NavItem(kit, "k", "info", "Label")
    item.resize(220, 40)
    item.set_badge("Soon")
    item.grab()
    item.set_active(True)
    item.grab()
    item.set_active(False)
    _enter(item)
    item.grab()
    item.set_active(True)
    _enter(item)
    item.grab()
    item.leaveEvent(QEvent(QEvent.Type.Leave))
    item.set_badge("")
    item.show()
    item.setFocus(Qt.FocusReason.TabFocusReason)
    qapp.processEvents()
    item.grab()
    item.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    item.set_rail(True)
    assert item.toolTip() == "Label"
    item.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    item.grab()
    item.set_rail(False)
    item.set_label("Other")
    assert item.toolTip() == ""
    assert item.sizeHint().height() > 0
    kit.zoom.zoom_in()
    item.close()


def test_nav_item_arrow_keys(kit: UiKit, qapp: QApplication) -> None:
    owner = _Owner()
    item = NavItem(kit, "k", "info", "Label", owner=owner)  # type: ignore[arg-type]
    QTest.keyClick(item, Qt.Key.Key_Down)
    QTest.keyClick(item, Qt.Key.Key_Up)
    QTest.keyClick(item, Qt.Key.Key_A)
    assert owner.steps == [1, -1]
    alone = NavItem(kit, "k", "info", "Label")
    QTest.keyClick(alone, Qt.Key.Key_Down)


def test_progress_bar_modes(kit: UiKit, qapp: QApplication) -> None:
    bar = ProgressBar(kit)
    bar.resize(200, 10)
    bar.set_value(None)
    bar.grab()
    bar._on_sweep(0.5)
    bar._on_sweep("x")
    bar.show()
    qapp.processEvents()
    assert bar._sweep.state() == bar._sweep.State.Running
    bar.set_value(None)
    bar.set_value(0.5)
    assert bar.value == 0.5
    bar._on_fill(0.4)
    bar._on_fill("x")
    bar.grab()
    bar.set_tone("danger")
    bar.grab()
    bar.set_value(2.0)
    assert bar.value == 1.0
    bar.set_value(None)
    bar._sync_sweep()
    bar._value = 0.5
    bar._sync_sweep()
    bar.hide()
    bar._sync_sweep()
    bar.set_tone("accent")
    bar.set_value(0.3)
    bar._sync_sweep()
    kit.zoom.zoom_in()
    bar.close()


def test_busy_stripe(kit: UiKit, qapp: QApplication) -> None:
    stripe = BusyStripe(kit)
    assert not stripe.isVisible()
    parent = QWidget()
    parent.show()
    stripe.setParent(parent)
    stripe.set_active(True)
    stripe.resize(100, 4)
    stripe.grab()
    stripe.set_active(False)
    parent.close()


def _options() -> list[SegmentOption]:
    return [
        SegmentOption("a", "A", hint="hint a", icon="info", tooltip="tip"),
        SegmentOption("b", "B", unavailable="not here"),
        SegmentOption("c", "", tooltip="icon only"),
    ]


def test_segmented_choose_and_unavailable(kit: UiKit, qapp: QApplication) -> None:
    seg = Segmented(kit, _options(), "a", label="Pick")
    seen: list[str] = []
    seg.selected.connect(seen.append)
    assert seg.value == "a"
    assert seg._caption.text() == "hint a"
    seg.choose(0)
    assert seen == []
    seg.choose(1)
    assert seg._caption.text() == "not here"
    assert seg.value == "a"
    seg.choose(2)
    assert seen == ["c"]
    assert seg._caption.isHidden()
    seg.set_value("a")
    seg.set_label("")
    seg.set_label("New")
    seg.set_options(_options())
    seg.set_options(_options(), "c")
    assert seg.value == "c"
    seg.set_value("zzz")
    assert seg._caption.isHidden()
    kit.zoom.zoom_in()


def test_segmented_arrow_keys(kit: UiKit, qapp: QApplication) -> None:
    seg = Segmented(kit, [SegmentOption("a", "A"), SegmentOption("c", "C")], "a", compact=True)
    seg.show()
    button = seg._buttons[0]
    QTest.keyClick(button, Qt.Key.Key_Right)
    assert seg.value == "c"
    QTest.keyClick(seg._buttons[1], Qt.Key.Key_Left)
    assert seg.value == "a"
    QTest.keyClick(button, Qt.Key.Key_Down)
    QTest.keyClick(button, Qt.Key.Key_Up)
    QTest.keyClick(button, Qt.Key.Key_A)
    seg.close()


def _sections() -> list[NavSection]:
    return [
        NavSection(
            "nav.section.main",
            (
                NavEntry("overview", "nav.overview", "info"),
                NavEntry("chats", "nav.chats", "info", badge_key="nav.soon"),
                NavEntry("locked", "nav.data", "info", locked_key="nav.soon"),
            ),
        )
    ]


def test_sidebar_navigation_and_locking(kit: UiKit, qapp: QApplication) -> None:
    bar = Sidebar(kit, _sections(), current="overview")
    navigated: list[str] = []
    locked: list[tuple[str, str]] = []
    bar.navigate.connect(navigated.append)
    bar.locked.connect(lambda key, why: locked.append((key, why)))
    assert bar.current == "overview"
    bar._items["chats"].click()
    assert navigated == ["chats"]
    assert bar.current == "chats"
    bar._items["locked"].click()
    assert locked
    assert locked[0][0] == "locked"
    assert bar.current == "chats"
    bar.set_badge("chats", "3")
    bar.set_badge("chats", None)
    bar.set_current(None)
    order_item = bar._items["overview"]
    bar.focus_neighbour(order_item, 1)
    bar.focus_neighbour(order_item, -1)
    bar.focus_neighbour(bar._toggle, 1)
    assert bar._toggle.key == COLLAPSE_KEY
    kit.language.set_language("ru")
    kit.theme.set_preference("dark")
    kit.zoom.zoom_in()
    assert bar.width() == bar._target_width()


def test_sidebar_collapse(kit: UiKit, qapp: QApplication) -> None:
    bar = Sidebar(kit, _sections(), collapsed=True)
    states: list[bool] = []
    bar.collapsed_changed.connect(states.append)
    assert bar.is_collapsed
    bar.set_collapsed(True)
    bar.set_collapsed(False, animate=False)
    assert not bar.is_collapsed
    assert bar.width() == bar._target_width()
    bar.set_collapsed(True, animate=False)
    bar.toggle()
    bar._on_width(40.0)
    bar._on_width("x")
    bar._anim.stop()
    bar._after_animation()
    bar.toggle()
    bar._anim.stop()
    bar._after_animation()
    assert states == [False, True, False, True]
    bar._toggle.click()
    bar._anim.stop()


def test_status_bar(kit: UiKit, qapp: QApplication) -> None:
    status = StatusBar(kit, "1.2.3")
    status.add_item(QWidget())
    status._zoom_in.click()
    status._zoom_out.click()
    status._zoom_value.click()
    assert "%" in status._zoom_value.text()
    kit.zoom.set_factor(1.5)
    kit.zoom.set_factor(0.5)
    kit.zoom.set_factor(3.0)
    kit.language.set_language("ru")
    kit.theme.set_preference("dark")
    assert "1.2.3" in status._version_label.text()


def test_switch_paint_and_focus(
    kit: UiKit, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Switch, "hasFocus", lambda self: True)
    switch = Switch(kit, checked=True)
    switch.resize(switch.sizeHint())
    assert switch.minimumSizeHint() == switch.sizeHint()
    switch.grab()
    switch.show()
    switch.setFocus(Qt.FocusReason.TabFocusReason)
    qapp.processEvents()
    switch.grab()
    switch.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))
    switch.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    switch.grab()
    switch.setEnabled(False)
    switch.grab()
    switch.setEnabled(True)
    switch.toggle()
    switch._on_slide(0.5)
    switch._on_slide("x")
    switch.grab()
    kit.zoom.zoom_in()
    switch.close()


def test_switch_row(kit: UiKit, qapp: QApplication) -> None:
    row = SwitchRow(kit, "Label", "Hint")
    toggled: list[bool] = []
    row.toggled.connect(toggled.append)
    row.show()
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
    assert row.is_checked()
    QTest.mouseClick(row, Qt.MouseButton.RightButton, pos=row.rect().center())
    assert row.is_checked()
    row.switch.setEnabled(False)
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
    assert row.is_checked()
    row.switch.setEnabled(True)
    row.set_checked(False)
    row.set_texts("L2")
    row.set_texts("L3", "H3")
    assert toggled == [True, False]
    assert SwitchRow(kit, "L").is_checked() is False
    kit.zoom.zoom_in()
    row.close()


def test_toast_lifecycle(kit: UiKit, qapp: QApplication) -> None:
    window = QWidget()
    window.resize(600, 400)
    host = ToastHost(kit, window)
    window.show()
    qapp.processEvents()
    first = host.push("danger", "Message", title="Title")
    host.push("warning", "w")
    plain = host.push("neutral", "n", timeout_ms=1000)
    assert host.count == 3
    assert first._timer.interval() == 12_000
    assert plain._timer.interval() == 1000
    window.resize(500, 300)
    qapp.processEvents()
    kit.theme.set_preference("dark")
    kit.zoom.zoom_in()
    plain.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    plain.leaveEvent(QEvent(QEvent.Type.Leave))
    assert plain._timer.isActive()
    plain.dismiss()
    plain.dismiss()
    plain.leaveEvent(QEvent(QEvent.Type.Leave))
    assert not plain._timer.isActive()
    plain._on_fade(0.5)
    plain._on_fade("x")
    assert host.count == 3
    plain._on_fade(0.0)
    assert host.count == 2
    host.remove(plain)
    first._close.click()
    first._leaving = True
    first._on_fade(0.0)
    assert host.count == 1
    host.push_key("success", "toast.dismiss")
    for _ in range(MAX_VISIBLE + 2):
        host.push("info", "x")
    assert host.count == MAX_VISIBLE
    host.clear()
    assert host.count == 0
    window.close()


def test_toast_is_a_frame(kit: UiKit, qapp: QApplication) -> None:
    window = QWidget()
    host = ToastHost(kit, window)
    toast = host.push("success", "ok")
    assert isinstance(toast, Toast)
    host.clear()
    window.close()


@pytest.mark.parametrize("switchers", [True, False])
def test_top_bar(kit: UiKit, qapp: QApplication, switchers: bool) -> None:
    bar = TopBar(kit, "Title", "Sub", switchers=switchers)
    bar.add_action(QWidget())
    bar.set_title("T2")
    bar.set_subtitle("")
    bar.set_subtitle("S2")
    assert (bar.theme_switcher is None) is (not switchers)
    kit.zoom.zoom_in()


def test_switchers_drive_managers(kit: UiKit, qapp: QApplication) -> None:
    theme = ThemeSwitcher(kit)
    language = LanguageSwitcher(kit)
    theme.choose(0)
    assert kit.theme.preference == "light"
    theme.choose(1)
    assert kit.theme.preference == "dark"
    theme.choose(2)
    assert kit.theme.preference == "system"
    assert theme.value == "system"
    language.choose(1)
    assert kit.language.current == "ru"
    language.choose(0)
    assert kit.language.current == "en"
    assert theme.accessibleName()
    assert language.value == "en"
