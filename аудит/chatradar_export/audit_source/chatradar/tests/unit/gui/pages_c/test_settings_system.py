from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from chatimport import __version__, autostart
from chatimport.gui.i18n import tr
from chatimport.gui.pages import settings_system as ss
from chatimport.gui.pages.settings_support import SettingsHooks

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from tests.unit.gui.pages_c.conftest import DeferredRunner, FakeAutostart

STATE = autostart.AutostartState


def startup(gui: GuiContext, hooks: SettingsHooks | None = None) -> ss.StartupCard:
    return ss.StartupCard(gui, hooks or SettingsHooks(autostart_task="T", executable="x.exe"))


def runner_of(card: ss.StartupCard) -> DeferredRunner:
    return card._runner  # type: ignore[return-value]  # replaced by the fixture


def test_unsupported_platform_disables_the_switch(
    gui: GuiContext, fake_autostart: FakeAutostart
) -> None:
    fake_autostart.supported = False
    card = startup(gui)
    assert not card._switch.isEnabled()
    assert card._chip.text == tr("settings.startup.state.unsupported")
    card.refresh()
    assert fake_autostart.calls == []
    assert not card._busy


def test_refresh_shows_each_state(gui: GuiContext, fake_autostart: FakeAutostart) -> None:
    card = startup(gui)
    runner = runner_of(card)

    card.refresh()
    assert card._busy
    card.retranslate()
    checking = card._chip.text
    assert checking == tr("settings.startup.state.checking")
    card.refresh()
    assert len(runner.pending) == 1
    runner.flush()
    assert fake_autostart.calls == ["status"]
    disabled = card._chip.text
    assert disabled != checking
    assert not card._switch.isChecked()

    fake_autostart.status_result = autostart.AutostartStatus(STATE.ENABLED, "cmd", True)
    card.refresh()
    runner.flush()
    assert card._switch.isChecked()
    assert card._chip.text not in (disabled, checking)
    assert card._update.isHidden()

    fake_autostart.status_result = autostart.AutostartStatus(STATE.ENABLED, "cmd", False)
    card.refresh()
    runner.flush()
    assert not card._update.isHidden()
    assert card._chip.text not in (disabled, checking)


def test_toggle_enables_then_disables(gui: GuiContext, fake_autostart: FakeAutostart) -> None:
    card = startup(gui)
    runner = runner_of(card)
    card._switch.click()
    assert fake_autostart.calls == ["enable"]
    assert not card._switch.isEnabled()
    card._apply(False)
    assert fake_autostart.calls == ["enable"]
    runner.flush()
    assert card._switch.isChecked()
    assert card._switch.isEnabled()

    card._switch.click()
    runner.flush()
    assert fake_autostart.calls == ["enable", "disable"]
    assert not card._switch.isChecked()


def test_update_button_reapplies(gui: GuiContext, fake_autostart: FakeAutostart) -> None:
    card = startup(gui)
    card._update.click()
    runner_of(card).flush()
    assert fake_autostart.calls == ["enable"]


@pytest.mark.parametrize("reason", ["denied", "failed", "unsupported"])
def test_known_failures_show_a_message(
    gui: GuiContext, fake_autostart: FakeAutostart, reason: str
) -> None:
    fake_autostart.status_result = autostart.AutostartError(reason, "no")  # type: ignore[arg-type]
    card = startup(gui)
    card._switch.click()
    runner_of(card).flush()
    assert not card.message.isHidden()
    assert not card._busy
    assert not card._switch.isChecked()


def test_unexpected_failure_shows_a_generic_message(
    gui: GuiContext, fake_autostart: FakeAutostart
) -> None:
    fake_autostart.status_result = RuntimeError("boom")
    card = startup(gui)
    card._switch.click()
    runner_of(card).flush()
    assert not card.message.isHidden()


def test_startup_retranslates(gui: GuiContext, kit: UiKit) -> None:
    card = startup(gui)
    before = card._update.text()
    kit.language.set_language("ru")
    assert card._update.text() != before


class FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


def test_about_shows_version_and_paths(gui: GuiContext) -> None:
    card = ss.AboutCard(gui, SettingsHooks())
    assert __version__ in card._version.text()
    shown = {name: row._path for name, row in card._rows.items()}
    ctx = gui.service
    assert shown == {
        "data": ctx.root,
        "config": ctx.paths.config_file,
        "library": ctx.library_file,
        "logs": ctx.paths.log_dir,
    }


def test_about_uses_the_control_context(control_gui: GuiContext) -> None:
    card = ss.AboutCard(control_gui, SettingsHooks())
    assert card._rows["data"]._path == control_gui.service.root


def test_path_row_copy_and_open(monkeypatch: pytest.MonkeyPatch, gui: GuiContext) -> None:
    clipboard = FakeClipboard()
    monkeypatch.setattr(ss, "QApplication", SimpleNamespace(clipboard=lambda: clipboard))
    opened: list[Path] = []
    monkeypatch.setattr(ss, "open_path", opened.append)
    row = ss.PathRow(gui.kit)
    row._copy_path()
    row._open_path()
    assert not clipboard.text
    assert opened == []

    target = Path("some") / "folder"
    row.set_path("Caption", target)
    row._copy.click()
    row._open.click()
    assert clipboard.text == str(target)
    assert opened == [target]


def test_about_retranslates(gui: GuiContext, kit: UiKit) -> None:
    card = ss.AboutCard(gui, SettingsHooks())
    before = card._rows["data"]._caption.text()
    kit.language.set_language("ru")
    assert card._rows["data"]._caption.text() != before
