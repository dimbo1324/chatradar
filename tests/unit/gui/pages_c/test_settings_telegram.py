from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLineEdit

from chatimport.config import ConfigError, load_config
from chatimport.gui.i18n import tr
from chatimport.gui.pages import settings_telegram as st
from chatimport.gui.pages.settings_support import SettingsHooks
from chatimport.gui.widgets.toast import ToastHost
from chatimport.telegram.session_probe import SessionInfo

if TYPE_CHECKING:
    from chatimport.context import ServiceContext
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit
    from tests.unit.gui.pages_c.conftest import DeferredRunner

HASH = "0123456789abcdef0123456789abcdef"
CREDENTIALS = f'[telegram]\napi_id = 4242\napi_hash = "{HASH}"\n'


class Probe:
    def __init__(self) -> None:
        self.result: SessionInfo | Exception | None = SessionInfo("@someone")
        self.contexts: list[ServiceContext] = []

    def __call__(self, ctx: ServiceContext) -> SessionInfo | None:
        self.contexts.append(ctx)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def probe() -> Probe:
    return Probe()


def card_of(gui: GuiContext, probe: Probe, *, saved: bool = False) -> st.TelegramCard:
    if saved:
        gui.service.paths.config_file.write_text(CREDENTIALS, encoding="utf-8")
    return st.TelegramCard(gui, SettingsHooks(probe=probe))


def runner_of(card: st.TelegramCard) -> DeferredRunner:
    return card._runner  # type: ignore[return-value]  # replaced by the fixture


def test_loads_nothing_from_a_missing_file(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    assert not card.dirty
    assert not card.credentials_saved
    assert card._state == "checking"
    assert not card._save.isEnabled()


def test_loads_saved_credentials(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    assert card._api_id.text() == "4242"
    assert card._api_hash.text() == HASH
    assert card.credentials_saved


def test_broken_config_loads_as_empty(gui: GuiContext, probe: Probe) -> None:
    gui.service.paths.config_file.write_text("[telegram\n", encoding="utf-8")
    card = card_of(gui, probe)
    assert card._api_id.text() == ""


def test_credentials_saved_needs_a_positive_numeric_id(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    card._baseline = ("", "")
    assert not card.credentials_saved
    card._baseline = ("abc", "h")
    assert not card.credentials_saved
    card._baseline = ("0", "h")
    assert not card.credentials_saved
    card._baseline = ("5", "h")
    assert card.credentials_saved


def test_typing_marks_dirty(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    card._api_id.setText("99")
    assert card.dirty
    assert card._save.isEnabled()
    assert card._status.text() == tr("settings.unsaved")
    card._api_id.setText("4242")
    assert not card.dirty


def test_reveal_toggles_echo_mode(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    assert card._api_hash.echoMode() == QLineEdit.EchoMode.Password
    card._reveal.click()
    assert card._api_hash.echoMode() == QLineEdit.EchoMode.Normal
    card._reveal.click()
    assert card._api_hash.echoMode() == QLineEdit.EchoMode.Password


def test_api_id_must_be_a_positive_number(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    for value in ("", "0"):
        card._api_id.setText(value)
        card._api_hash.setText(HASH)
        card.save()
        assert not card.message.isHidden()
        assert not gui.service.paths.config_file.exists()


def test_api_hash_must_look_like_a_hash(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    card._api_id.setText("12")
    card._api_hash.setText("short")
    card.save()
    assert not card.message.isHidden()
    assert not gui.service.paths.config_file.exists()


def test_save_writes_the_credentials(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    saved: list[None] = []
    card.saved.connect(lambda: saved.append(None))
    card._api_id.setText(" 777 ")
    card._api_hash.setText(HASH)
    card.save()
    telegram = load_config(gui.service.paths.config_file).telegram
    assert telegram.api_id == 777
    assert telegram.api_hash == HASH
    assert saved == [None]
    assert not card.dirty
    assert not card.message.isHidden()
    assert card._state == "signed_out"


@pytest.mark.parametrize("error", [ConfigError("bad"), OSError("disk")])
def test_write_failures_become_messages(
    gui: GuiContext, probe: Probe, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def refuse(*_: object) -> None:
        raise error

    monkeypatch.setattr(st, "update_config", refuse)
    card = card_of(gui, probe)
    card._api_id.setText("5")
    card._api_hash.setText(HASH)
    saved: list[None] = []
    card.saved.connect(lambda: saved.append(None))
    card.save()
    assert not card.message.isHidden()
    assert card.dirty
    assert not saved


def test_refresh_without_credentials(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    card.refresh_session()
    assert card._state == "no_credentials"
    assert not card._sign_in.isEnabled()
    assert card._sign_in.toolTip() != ""


def test_refresh_while_service_runs_trusts_it(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    card._handle = "@kept"
    card._service = "running"
    card.refresh_session()
    assert card._state == "signed_in"
    assert "@kept" in card._chip.text
    assert card._recheck.isHidden()


def test_refresh_without_a_session_file(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    card.refresh_session()
    assert card._state == "signed_out"
    assert not card._sign_in.isHidden()
    assert card._sign_in.isEnabled()
    assert probe.contexts == []


def test_probe_signed_in_signed_out_and_failure(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    gui.service.paths.session_file.write_bytes(b"x")
    runner = runner_of(card)

    card.refresh_session()
    assert card._state == "checking"
    card.refresh_session()
    assert len(runner.pending) == 1
    runner.flush()
    assert card._state == "signed_in"
    assert "@someone" in card._chip.text
    assert probe.contexts[0].config.telegram.api_id == 4242

    probe.result = None
    card.refresh_session()
    runner.flush()
    assert card._state == "signed_out"

    probe.result = RuntimeError("offline")
    card.refresh_session()
    runner.flush()
    assert card._state == "unknown"
    assert not card._recheck.isHidden()
    assert card._sign_in.isEnabled()


def test_probe_without_permission_does_not_run(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    gui.service.paths.session_file.write_bytes(b"x")
    card.refresh_session(allow_probe=False)
    assert runner_of(card).pending == []


def test_fresh_context_survives_a_broken_config(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    gui.service.paths.session_file.write_bytes(b"x")
    gui.service.paths.config_file.write_text("[telegram\n", encoding="utf-8")
    card.refresh_session()
    runner_of(card).flush()
    assert probe.contexts == [gui.service]


def test_service_state_change_refreshes_once(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    card.set_service_state("running")
    assert card._state == "signed_in"
    card._state = "unknown"
    card.set_service_state("running")
    assert card._state == "unknown"
    card.set_service_state("stopped")
    assert card._state == "signed_out"


def test_link_opens_the_apps_page(
    gui: GuiContext, probe: Probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(st, "open_link", opened.append)
    card = card_of(gui, probe)
    card._link.click()
    assert opened == [st.TELEGRAM_APPS_URL]


def test_recheck_button_probes_again(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    gui.service.paths.session_file.write_bytes(b"x")
    card._set_session("unknown")
    card._recheck.click()
    assert len(runner_of(card).pending) == 1


class FakeLoginDialog(QObject):
    signed_in = Signal(str)
    created: ClassVar[list[FakeLoginDialog]] = []

    def __init__(self, gui: Any, hooks: Any, control: Any, parent: Any) -> None:
        super().__init__()
        self.args = (gui, hooks, control, parent)
        self.executed = False
        FakeLoginDialog.created.append(self)

    def exec(self) -> int:
        self.executed = True
        self.signed_in.emit("@newcomer")
        return 1


def test_sign_in_opens_the_dialog_and_reports(
    gui: GuiContext, probe: Probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeLoginDialog.created.clear()
    monkeypatch.setattr(st, "LoginDialog", FakeLoginDialog)
    card = card_of(gui, probe, saved=True)
    toasts = ToastHost(gui.kit, card)
    heard: list[str] = []
    card.signed_in.connect(heard.append)
    card._set_session("signed_out")
    card._sign_in.click()
    (dialog,) = FakeLoginDialog.created
    assert dialog.executed
    assert dialog.args[0] is gui
    assert heard == ["@newcomer"]
    assert card._state == "signed_in"
    assert "@newcomer" in card._chip.text
    assert toasts.count == 1


def test_retranslate(gui: GuiContext, probe: Probe, kit: UiKit) -> None:
    card = card_of(gui, probe)
    before = card._save.text()
    kit.language.set_language("ru")
    assert card._save.text() != before
