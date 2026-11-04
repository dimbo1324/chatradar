from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport.gui import key_guide
from chatimport.gui.i18n import tr
from chatimport.gui.pages import settings_telegram as st
from chatimport.gui.pages.settings_support import SettingsHooks
from tests.unit.gui.pages_c.test_settings_telegram import HASH, Probe, card_of, probe

if TYPE_CHECKING:
    import pytest

    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit

__all__ = ["probe"]


def test_inline_errors_follow_the_typing(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    assert card._id_error.isHidden()
    assert card._hash_error.isHidden()
    card._api_id.setText("12")
    card._api_hash.setText("abc")
    assert card._id_error.isHidden()
    assert card._hash_error.text() == tr("settings.tg.err.api_hash")
    assert not card._hash_error.isHidden()
    card._api_hash.setText(HASH)
    assert card._hash_error.isHidden()
    assert card._hash_error.text() == ""


def test_save_is_disabled_while_a_value_is_invalid(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe)
    card._api_id.setText("12")
    assert not card._save.isEnabled()
    card._api_hash.setText("short")
    assert not card._save.isEnabled()
    card._api_hash.setText(HASH)
    assert card._save.isEnabled()
    card._api_hash.setText(HASH.upper())
    assert card._save.isEnabled()
    card._api_hash.setText(HASH + "0")
    assert not card._save.isEnabled()


def test_sign_in_is_disabled_while_the_inputs_are_invalid(gui: GuiContext, probe: Probe) -> None:
    card = card_of(gui, probe, saved=True)
    card.refresh_session()
    assert card._state == "signed_out"
    assert card._sign_in.isEnabled()
    card._api_hash.setText("oops")
    assert not card._sign_in.isEnabled()
    card._api_hash.setText(HASH)
    assert card._sign_in.isEnabled()


def test_a_legacy_hash_is_flagged_on_load(gui: GuiContext, probe: Probe) -> None:
    gui.service.paths.config_file.write_text(
        '[telegram]\napi_id = 5\napi_hash = "abcdefghijklmnop"\n', encoding="utf-8"
    )
    card = st.TelegramCard(gui, SettingsHooks(probe=probe))
    assert not card._hash_error.isHidden()
    assert not card._save.isEnabled()


def test_language_change_retranslates_the_errors(gui: GuiContext, probe: Probe, kit: UiKit) -> None:
    card = card_of(gui, probe)
    card._api_hash.setText("bad")
    english = card._hash_error.text()
    kit.language.set_language("ru")
    assert card._hash_error.text() != english
    assert card._hash_error.text() == tr("settings.tg.err.api_hash")


def test_the_guide_button_opens_the_guide(
    gui: GuiContext, probe: Probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[object] = []

    def fake_exec(self: key_guide.KeyGuideDialog) -> int:
        opened.append(self)
        return 0

    monkeypatch.setattr(key_guide.KeyGuideDialog, "exec", fake_exec)
    card = card_of(gui, probe)
    assert card._guide.text() == tr("setup.keys.guide")
    card._guide.click()
    assert len(opened) == 1
