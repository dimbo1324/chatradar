from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from chatimport.gui import main_window
from chatimport.gui.main_window import MainWindow
from chatimport.gui.notifier import QtNotifier
from chatimport.gui.pages.settings_support import SettingsHooks
from tests.unit.gui.shell.test_main_window import make_pages

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from tests.unit.gui.conftest import FakeBridge

NEEDS_SETUP: dict[str, Any] = {"service": "needs_setup", "chats": [], "errors": []}


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, object]]:
    calls: list[tuple[object, object]] = []

    def fake_exec(self: main_window.SetupWizard) -> int:
        calls.append((self.parentWidget(), self.gui))
        return 0

    monkeypatch.setattr(main_window.SetupWizard, "exec", fake_exec)
    return calls


def test_the_banner_button_opens_the_wizard(
    gui: GuiContext, bridge: FakeBridge, opened: list[tuple[object, object]]
) -> None:
    bridge.last_snapshot = NEEDS_SETUP
    window = MainWindow(gui, make_pages(), QtNotifier(), hooks=SettingsHooks())
    assert not window._banner.isHidden()
    window._setup_button.click()
    assert opened == [(window, gui)]


def test_the_wizard_is_offered_once_per_run(
    gui: GuiContext, bridge: FakeBridge, opened: list[tuple[object, object]]
) -> None:
    bridge.last_snapshot = NEEDS_SETUP
    window = MainWindow(gui, make_pages(), QtNotifier())
    assert opened == []
    window.offer_setup_wizard()
    window.offer_setup_wizard()
    assert len(opened) == 1


def test_the_wizard_is_not_offered_when_unneeded(
    gui: GuiContext, bridge: FakeBridge, opened: list[tuple[object, object]]
) -> None:
    window = MainWindow(gui, make_pages(), QtNotifier())
    window.offer_setup_wizard()
    bridge.last_snapshot = {"service": "running", "chats": [], "errors": []}
    window.offer_setup_wizard()
    assert opened == []
    bridge.last_snapshot = NEEDS_SETUP
    gui.settings.update(setup_completed=True)
    window.offer_setup_wizard()
    assert opened == []
