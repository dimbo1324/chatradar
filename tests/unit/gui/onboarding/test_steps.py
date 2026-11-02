from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QFileDialog

from chatimport import autostart
from chatimport.config import ConfigError, load_config
from chatimport.gui import key_guide, setup_steps, setup_steps_data
from chatimport.gui.i18n import tr
from chatimport.gui.pages.settings_support import SettingsHooks
from chatimport.gui.setup_steps import KeysStep, SignInStep, WizardEnv, WizardStep
from chatimport.gui.setup_steps_data import ChatsStep, FolderStep
from chatimport.gui.setup_steps_run import RunModeStep, SummaryStep
from chatimport.library import load_library
from tests.unit.gui.onboarding.conftest import FakeLoginDialog

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from tests.unit.gui.onboarding.conftest import DeferredRunner, FakeAutostart, FakeControl

HASH = "0123456789abcdef0123456789abcdef"


def env_of(gui: GuiContext, control: FakeControl | None = None) -> WizardEnv:
    return WizardEnv(gui, SettingsHooks(autostart_task="T", executable="x.exe"), control)


def config_file(gui: GuiContext) -> Path:
    return gui.service.paths.config_file


def test_base_step_defaults(gui: GuiContext) -> None:
    class Plain(WizardStep):
        name = "keys"

    step = Plain(env_of(gui))
    step.retranslate()
    step.enter()
    assert step.can_advance()
    assert step.commit()
    assert not step.skippable
    assert step.env.context is gui.service


def test_keys_step_validates_and_saves(gui: GuiContext) -> None:
    step = KeysStep(env_of(gui))
    changes: list[None] = []
    step.changed.connect(lambda: changes.append(None))
    assert not step.can_advance()
    assert not step.commit()
    step._api_id.setText("42")
    step._api_hash.setText("xyz")
    assert changes
    assert not step._hash_error.isHidden()
    assert not step.can_advance()
    step._api_hash.setText(HASH)
    assert step._hash_error.isHidden()
    assert step.can_advance()
    assert step.commit()
    telegram = load_config(config_file(gui)).telegram
    assert (telegram.api_id, telegram.api_hash) == (42, HASH)


def test_keys_step_skips_the_write_when_nothing_changed(
    gui: GuiContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file(gui).write_text(f'[telegram]\napi_id = 7\napi_hash = "{HASH}"\n', encoding="utf-8")
    step = KeysStep(env_of(gui))
    step.enter()
    assert step._api_id.text() == "7"
    assert step._api_hash.text() == HASH

    def refuse(*_: object) -> None:
        raise AssertionError("must not write")

    monkeypatch.setattr(setup_steps, "update_config", refuse)
    assert step.commit()


def test_keys_step_enter_keeps_what_was_typed_and_survives_a_broken_file(
    gui: GuiContext,
) -> None:
    config_file(gui).write_text(f'[telegram]\napi_id = 7\napi_hash = "{HASH}"\n', encoding="utf-8")
    step = KeysStep(env_of(gui))
    step._api_id.setText("99")
    step.enter()
    assert step._api_id.text() == "99"
    assert step._api_hash.text() == HASH
    config_file(gui).write_text("[telegram\n", encoding="utf-8")
    other = KeysStep(env_of(gui))
    other.enter()
    assert other._api_id.text() == ""
    other._api_id.setText("5")
    other._api_hash.setText(HASH)
    assert not other.commit()
    assert not other._problem.isHidden()


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (ConfigError("bad"), "setup.keys.error.rejected"),
        (OSError("disk"), "setup.keys.error.write"),
    ],
)
def test_keys_step_reports_write_failures(
    gui: GuiContext, monkeypatch: pytest.MonkeyPatch, error: Exception, key: str
) -> None:
    def refuse(*_: object) -> None:
        raise error

    monkeypatch.setattr(setup_steps, "update_config", refuse)
    step = KeysStep(env_of(gui))
    step._api_id.setText("5")
    step._api_hash.setText(HASH)
    assert not step.commit()
    assert not step._problem.isHidden()
    assert step._problem._body.text() == tr(key)
    step._api_id.setText("6")
    assert step._problem.isHidden()


def test_keys_step_reveal_guide_and_language(
    gui: GuiContext, monkeypatch: pytest.MonkeyPatch, kit: UiKit
) -> None:
    opened: list[object] = []

    def fake_exec(self: key_guide.KeyGuideDialog) -> int:
        opened.append(self)
        return 0

    monkeypatch.setattr(key_guide.KeyGuideDialog, "exec", fake_exec)
    step = KeysStep(env_of(gui))
    assert step._api_hash.echoMode().name == "Password"
    step._reveal.click()
    assert step._api_hash.echoMode().name == "Normal"
    step._reveal.click()
    step._guide.click()
    assert len(opened) == 1
    step._api_hash.setText("bad")
    before = step._hash_error.text()
    kit.language.set_language("ru")
    assert step._hash_error.text() != before


def test_sign_in_step_needs_keys_first(gui: GuiContext) -> None:
    step = SignInStep(env_of(gui))
    step.enter()
    assert not step._button.isEnabled()
    assert not step._note.isHidden()
    assert not step.can_advance()
    assert step.skippable


def test_sign_in_step_signs_in(gui: GuiContext) -> None:
    config_file(gui).write_text(f'[telegram]\napi_id = 7\napi_hash = "{HASH}"\n', encoding="utf-8")
    step = SignInStep(env_of(gui))
    changes: list[None] = []
    step.changed.connect(lambda: changes.append(None))
    step.enter()
    assert step._button.isEnabled()
    assert step._note.isHidden()
    step._button.click()
    (dialog,) = FakeLoginDialog.created
    assert dialog.args[0] is gui
    assert step.can_advance()
    assert "@newcomer" in step._chip.text
    assert step._button.isHidden()
    assert len(changes) >= 2


def test_sign_in_step_recognises_an_existing_session(gui: GuiContext) -> None:
    gui.service.paths.session_file.write_bytes(b"x")
    step = SignInStep(env_of(gui))
    step.enter()
    assert step.can_advance()
    assert step._chip.text == tr("setup.signin.done")
    step.retranslate()


def test_chats_step_adds_links_and_reports_each_line(gui: GuiContext) -> None:
    step = ChatsStep(env_of(gui))
    step.enter()
    assert not step.can_advance()
    assert step._known.isHidden()
    step._add.click()
    assert not step._empty.isHidden()
    step._input.setPlainText("@alpha_chat\nhello\nhttps://t.me/beta_chat")
    step._add.click()
    assert step._empty.isHidden()
    assert step._input.toPlainText() == "hello"
    assert len(load_library(gui.service.library_file).entries) == 2
    assert step.can_advance()
    assert not step._known.isHidden()
    assert step._results.count() == 3
    step._input.setPlainText("@alpha_chat")
    step._add.click()
    assert step._results.count() == 1
    step.retranslate()


def test_chats_step_keeps_failed_lines_for_a_retry(gui: GuiContext) -> None:
    gui.service.library_file.write_text("[[chat]\n", encoding="utf-8")
    step = ChatsStep(env_of(gui))
    step._input.setPlainText("@alpha_chat")
    step._add.click()
    assert step._input.toPlainText() == "@alpha_chat"
    assert not step.can_advance()


def test_folder_step_defaults_and_saves_a_new_folder(gui: GuiContext, tmp_path: Path) -> None:
    step = FolderStep(env_of(gui))
    step.enter()
    assert step._path.text() == str(tmp_path / "ChatImport")
    assert step.can_advance()
    assert step.commit()
    assert not config_file(gui).exists()
    target = tmp_path / "elsewhere"
    step._path.setText(str(target))
    step._path.editingFinished.emit()
    assert step._check.changed
    assert step.commit()
    assert load_config(config_file(gui)).output.root_dir == str(target / "ChatImport")
    step.retranslate()
    assert "elsewhere" in step._verdict._body.text()


def test_folder_step_rejects_the_application_folder(gui: GuiContext) -> None:
    step = FolderStep(env_of(gui))
    step.enter()
    step._path.setText(str(gui.service.paths.base))
    step._path.editingFinished.emit()
    assert not step.can_advance()
    assert not step.commit()
    assert step._verdict._body.text().startswith(tr("setup.folder.invalid", detail="")[:10])


def test_folder_step_warns_about_cloud_folders(gui: GuiContext, tmp_path: Path) -> None:
    step = FolderStep(env_of(gui))
    step.enter()
    step._path.setText(str(tmp_path / "OneDrive" / "Archive"))
    step._path.editingFinished.emit()
    assert not step._cloud.isHidden()
    assert step.can_advance()
    step._path.setText(str(tmp_path / "plain"))
    step._path.editingFinished.emit()
    assert step._cloud.isHidden()


def test_folder_step_browse(
    gui: GuiContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[str] = []
    answers = [str(tmp_path / "picked"), ""]

    def fake_pick(parent: object, caption: str, start: str) -> str:
        starts.append(start)
        return answers.pop(0)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(fake_pick))
    step = FolderStep(env_of(gui))
    step._browse.click()
    assert starts == [str(tmp_path / "ChatImport")]
    assert step._path.text() == str(tmp_path / "picked")
    assert step._check.path == tmp_path / "picked" / "ChatImport"
    step._browse.click()
    assert starts[1] == str(tmp_path / "picked")
    assert step._path.text() == str(tmp_path / "picked")


def test_folder_step_reports_a_failed_save(
    gui: GuiContext, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object) -> None:
        raise OSError("locked")

    monkeypatch.setattr(setup_steps_data, "set_output_root", refuse)
    step = FolderStep(env_of(gui))
    step.enter()
    step._path.setText(str(tmp_path / "elsewhere"))
    assert not step.commit()
    assert not step._problem.isHidden()
    step._path.editingFinished.emit()
    assert step._problem.isHidden()


def test_run_mode_default_and_apply(gui: GuiContext, fake_autostart: FakeAutostart) -> None:
    step = RunModeStep(env_of(gui))
    runner: DeferredRunner = step._runner  # type: ignore[assignment]
    assert step.autostart_chosen
    results: list[bool] = []
    step.apply(results.append)
    runner.flush()
    assert fake_autostart.calls == ["enable"]
    assert results == [True]
    step._manual.setChecked(True)
    assert not step.autostart_chosen
    step.apply(results.append)
    runner.flush()
    assert fake_autostart.calls == ["enable", "disable"]
    assert results == [True, True]
    step.retranslate()


@pytest.mark.parametrize("error", [autostart.AutostartError("denied", "no"), RuntimeError("boom")])
def test_run_mode_reports_failures(
    gui: GuiContext, fake_autostart: FakeAutostart, error: Exception
) -> None:
    fake_autostart.status_result = error
    step = RunModeStep(env_of(gui))
    runner: DeferredRunner = step._runner  # type: ignore[assignment]
    results: list[bool] = []
    step.apply(results.append)
    runner.flush()
    assert results == [False]


def test_run_mode_without_autostart_support(gui: GuiContext, fake_autostart: FakeAutostart) -> None:
    fake_autostart.supported = False
    step = RunModeStep(env_of(gui))
    assert not step._auto.isEnabled()
    assert not step.autostart_chosen
    assert not step._unsupported.isHidden()
    results: list[bool] = []
    step.apply(results.append)
    assert results == [True]
    assert fake_autostart.calls == []


def test_summary_reflects_the_saved_state(gui: GuiContext, tmp_path: Path) -> None:
    mode = RunModeStep(env_of(gui))
    step = SummaryStep(env_of(gui), mode)
    step.enter()
    texts = [line.text() for line in step._lines]
    assert texts[0] == tr("setup.summary.keys.missing")
    assert texts[1] == tr("setup.summary.signin.missing")
    assert texts[4] == tr("setup.summary.mode.auto")
    assert not step._incomplete.isHidden()
    config_file(gui).write_text(f'[telegram]\napi_id = 7\napi_hash = "{HASH}"\n', encoding="utf-8")
    gui.service.paths.session_file.write_bytes(b"x")
    mode._manual.setChecked(True)
    step.enter()
    texts = [line.text() for line in step._lines]
    assert texts[0] == tr("setup.summary.keys.ok")
    assert texts[1] == tr("setup.summary.signin.ok")
    assert texts[4] == tr("setup.summary.mode.manual")
    assert step._incomplete.isHidden()
    assert str(tmp_path / "ChatImport") in texts[3]
    step.retranslate()


def test_folder_step_enter_keeps_a_typed_path(gui: GuiContext, tmp_path: Path) -> None:
    step = FolderStep(env_of(gui))
    step._path.setText(str(tmp_path / "typed"))
    step.enter()
    assert step._path.text() == str(tmp_path / "typed")
