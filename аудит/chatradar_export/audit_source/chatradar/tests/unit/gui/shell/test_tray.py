# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

import chatimport.gui.main_window as main_window
from chatimport.gui.i18n import tr
from chatimport.gui.tray import TOOLTIP_LIMIT, QtTray, make_tray_icon
from chatimport.runtime import Level

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from chatimport.gui.kit import UiKit


_ = main_window


class FakeIcon:
    def __init__(self) -> None:
        self.visible = False
        self.icons = 0
        self.tooltip = ""
        self.messages: list[tuple[str, str, Any]] = []

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False

    def isVisible(self) -> bool:
        return self.visible

    def setIcon(self, icon: object) -> None:
        self.icons += 1

    def setToolTip(self, text: str) -> None:
        self.tooltip = text

    def showMessage(self, title: str, message: str, icon: Any) -> None:
        self.messages.append((title, message, icon))


def make_tray(kit: UiKit, available: bool, monkeypatch: pytest.MonkeyPatch) -> QtTray:
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: available))
    tray = QtTray(kit)
    tray._icon = FakeIcon()  # type: ignore[assignment]
    return tray


@pytest.mark.parametrize("state", ["running", "paused", "error", "unknown"])
def test_make_tray_icon(qapp: QApplication, state: str) -> None:
    assert not make_tray_icon(state).isNull()


def test_unavailable_tray_is_a_no_op(
    kit: UiKit, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    tray = make_tray(kit, False, monkeypatch)
    tray.show()
    assert not tray.visible
    tray._icon.show()
    assert not tray.visible
    tray.show_message(Level.INFO, "T", "M")
    assert tray._icon.messages == []  # type: ignore[attr-defined]
    tray.hide()


def test_available_tray_shows_and_messages(
    kit: UiKit, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    tray = make_tray(kit, True, monkeypatch)
    icon: FakeIcon = tray._icon  # type: ignore[assignment]
    tray.show_message(Level.INFO, "T", "hidden")
    assert icon.messages == []
    tray.show()
    assert tray.visible
    for level in Level:
        tray.show_message(level, "T", "M")
    assert len(icon.messages) == 3
    tray.hide()
    assert not tray.visible


def test_status_tooltip_and_icon(
    kit: UiKit, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    tray = make_tray(kit, True, monkeypatch)
    icon: FakeIcon = tray._icon  # type: ignore[assignment]
    tray.set_status("running", "", paused=False)
    assert icon.icons == 0
    assert icon.tooltip == "ChatImport"
    tray.set_status("paused", "Paused - 2 chats", paused=True)
    assert icon.icons == 1
    assert "Paused" in icon.tooltip
    assert tray._toggle.text() == tr("shell.tray.resume")
    tray.set_status("error", "x" * 500, paused=False)
    assert len(icon.tooltip) == TOOLTIP_LIMIT
    kit.language.set_language("ru")
    assert tray._open.text()


def test_actions_and_activation_emit_requests(
    kit: UiKit, qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    tray = make_tray(kit, True, monkeypatch)
    fired: list[str] = []
    tray.open_requested.connect(lambda: fired.append("open"))
    tray.toggle_pause_requested.connect(lambda: fired.append("pause"))
    tray.recheck_requested.connect(lambda: fired.append("recheck"))
    tray.quit_requested.connect(lambda: fired.append("quit"))
    for action in (tray._open, tray._toggle, tray._recheck, tray._quit):
        action.trigger()
    tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert fired == ["open", "pause", "recheck", "quit", "open"]
