from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport.gui import setup_wizard
from chatimport.gui.i18n import tr
from chatimport.gui.pages import settings_system as ss
from chatimport.gui.pages.settings_support import SettingsHooks

HASH = "0123456789abcdef0123456789abcdef"

if TYPE_CHECKING:
    import pytest

    from chatimport.gui.context import GuiContext


def test_about_offers_the_wizard_again(gui: GuiContext, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    result = [1]

    def fake_exec(self: object) -> int:
        calls.append(self)
        return result[0]

    monkeypatch.setattr(setup_wizard.SetupWizard, "exec", fake_exec)
    card = ss.AboutCard(gui, SettingsHooks())
    finished: list[None] = []
    card.wizard_finished.connect(lambda: finished.append(None))
    assert card._rerun.text() == tr("setup.about.rerun")
    card._rerun.click()
    assert len(calls) == 1
    assert finished == [None]
    result[0] = 0
    card._rerun.click()
    assert len(calls) == 2
    assert finished == [None]


def test_the_page_reloads_after_the_wizard(gui: GuiContext) -> None:
    from chatimport.gui.pages.settings import SettingsPage

    page = SettingsPage(gui, hooks=SettingsHooks())
    gui.service.paths.config_file.write_text(
        f'[telegram]\napi_id = 9\napi_hash = "{HASH}"\n',
        encoding="utf-8",
    )
    page.about.wizard_finished.emit()
    assert page.telegram._api_id.text() == "9"
