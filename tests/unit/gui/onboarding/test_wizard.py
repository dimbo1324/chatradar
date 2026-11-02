from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from chatimport import autostart
from chatimport.config import load_config
from chatimport.gui import setup_steps
from chatimport.gui.i18n import tr
from chatimport.gui.pages.settings_support import SettingsHooks
from chatimport.gui.setup_wizard import SetupWizard
from chatimport.gui.widgets.toast import ToastHost
from tests.unit.gui.onboarding.conftest import FakeLoginDialog

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from tests.unit.gui.onboarding.conftest import DeferredRunner, FakeAutostart, FakeControl

HASH = "0123456789abcdef0123456789abcdef"


def runner_of(wizard: SetupWizard) -> DeferredRunner:
    return wizard._mode._runner  # type: ignore[return-value]  # replaced by the fixture


def test_a_fresh_run_through_every_step(
    control_gui: GuiContext,
    control: FakeControl,
    fake_autostart: FakeAutostart,
    tmp_path: Path,
) -> None:
    wizard = SetupWizard(control_gui, SettingsHooks(autostart_task="T"))
    assert wizard.index == 0
    assert wizard._back.isHidden()
    assert not wizard._next.isEnabled()
    assert wizard._skip.isHidden()
    keys = wizard.steps[0]
    keys._api_id.setText("42")  # type: ignore[attr-defined]
    keys._api_hash.setText(HASH)  # type: ignore[attr-defined]
    assert wizard._next.isEnabled()
    wizard._next.click()
    assert load_config(control_gui.service.paths.config_file).telegram.api_id == 42

    assert wizard.index == 1
    assert not wizard._back.isHidden()
    assert not wizard._skip.isHidden()
    assert wizard._next.isHidden()
    wizard.steps[1]._button.click()  # type: ignore[attr-defined]
    assert FakeLoginDialog.created
    assert wizard._skip.isHidden()
    wizard._next.click()

    assert wizard.index == 2
    assert not wizard._skip.isHidden()
    wizard.steps[2]._input.setPlainText("@alpha_chat")  # type: ignore[attr-defined]
    wizard.steps[2]._add.click()  # type: ignore[attr-defined]
    assert wizard._skip.isHidden()
    wizard._next.click()

    assert wizard.index == 3
    wizard.steps[3]._path.setText(str(tmp_path / "elsewhere"))  # type: ignore[attr-defined]
    wizard._next.click()
    assert load_config(control_gui.service.paths.config_file).output.root_dir.endswith("ChatImport")

    assert wizard.index == 4
    wizard._mode._manual.setChecked(True)
    wizard._next.click()

    assert wizard.index == 5
    assert wizard._next.isHidden()
    assert not wizard._finish.isHidden()
    assert wizard._counter.text() == tr("setup.wizard.step_of", n=6, total=6)
    wizard._finish.click()
    assert not wizard._finish.isEnabled()
    runner_of(wizard).flush()
    assert fake_autostart.calls == ["disable"]
    assert control_gui.settings.settings.setup_completed
    assert control.alive
    assert wizard.result() == 1


def test_finish_restarts_a_running_service(
    control_gui: GuiContext, control: FakeControl, fake_autostart: FakeAutostart
) -> None:
    control.alive = True
    wizard = SetupWizard(control_gui)
    wizard._show(5)
    wizard._finish.click()
    runner_of(wizard).flush()
    assert control.restarts == 1
    assert fake_autostart.calls == ["enable"]


def test_finish_without_a_service_control(gui: GuiContext) -> None:
    wizard = SetupWizard(gui)
    wizard._show(5)
    wizard._finish.click()
    runner_of(wizard).flush()
    assert gui.settings.settings.setup_completed


def test_a_failed_autostart_toasts_but_still_finishes(
    gui: GuiContext, fake_autostart: FakeAutostart
) -> None:
    fake_autostart.status_result = autostart.AutostartError("failed", "x")
    parent = QWidget()
    toasts = ToastHost(gui.kit, parent)
    wizard = SetupWizard(gui, parent=parent)
    wizard._show(5)
    wizard._finish.click()
    runner_of(wizard).flush()
    assert toasts.count == 1
    assert gui.settings.settings.setup_completed


def test_a_failed_autostart_without_a_parent_is_silent(
    gui: GuiContext, fake_autostart: FakeAutostart
) -> None:
    fake_autostart.status_result = autostart.AutostartError("failed", "x")
    wizard = SetupWizard(gui)
    wizard._show(5)
    wizard._finish.click()
    runner_of(wizard).flush()
    assert gui.settings.settings.setup_completed


def test_every_step_works_when_earlier_ones_were_done(gui: GuiContext, tmp_path: Path) -> None:
    gui.service.paths.config_file.write_text(
        f'[telegram]\napi_id = 7\napi_hash = "{HASH}"\n', encoding="utf-8"
    )
    gui.service.paths.session_file.write_bytes(b"x")
    gui.service.library_file.write_text('[[chat]]\nref = "@alpha_chat"\n', encoding="utf-8")
    wizard = SetupWizard(gui)
    assert wizard._next.isEnabled()
    wizard._next.click()
    assert wizard.index == 1
    assert wizard._next.isEnabled()
    wizard._next.click()
    assert wizard._next.isEnabled()
    wizard._next.click()
    assert wizard.steps[3]._path.text() == str(tmp_path / "ChatImport")  # type: ignore[attr-defined]
    wizard._next.click()
    wizard._next.click()
    assert wizard.index == 5
    assert wizard.steps[5]._incomplete.isHidden()  # type: ignore[attr-defined]


def test_back_skip_and_cancel(gui: GuiContext) -> None:
    wizard = SetupWizard(gui)
    wizard._show(1)
    wizard._skip.click()
    assert wizard.index == 2
    wizard._back.click()
    assert wizard.index == 1
    wizard._show(0)
    wizard._next.click()
    assert wizard.index == 0
    wizard.show()
    wizard._cancel.click()
    assert wizard.result() == 0
    assert not gui.settings.settings.setup_completed


def test_the_wizard_follows_the_language(gui: GuiContext, kit: UiKit) -> None:
    wizard = SetupWizard(gui)
    before = wizard._chips[0].text
    kit.language.set_language("ru")
    assert wizard._chips[0].text != before
    assert wizard.windowTitle() == tr("setup.wizard.title")
    assert wizard._chips[0].text.startswith("1. ")


def test_next_stays_when_the_step_cannot_save(
    gui: GuiContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise OSError("locked")

    monkeypatch.setattr(setup_steps, "update_config", refuse)
    wizard = SetupWizard(gui)
    keys = wizard.steps[0]
    keys._api_id.setText("42")  # type: ignore[attr-defined]
    keys._api_hash.setText(HASH)  # type: ignore[attr-defined]
    wizard._next.click()
    assert wizard.index == 0
