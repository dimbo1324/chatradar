from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.gui import key_guide
from chatimport.gui.i18n import tr
from chatimport.gui.key_guide import SITE_URL, KeyGuideDialog
from chatimport.gui.key_guide_art import KINDS, SchemeArt

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit


def test_the_guide_lists_seven_steps_and_warnings(gui: GuiContext) -> None:
    dialog = KeyGuideDialog(gui)
    assert len(dialog.steps) == 7
    assert dialog.windowTitle() == tr("setup.guide.title")
    assert dialog.steps[0].open_button is not None
    assert all(step.open_button is None for step in dialog.steps[1:])
    for number, step in enumerate(dialog.steps, start=1):
        assert step._title.text() == tr(f"setup.guide.step.{number}.title")


def test_the_open_button_goes_to_the_site(gui: GuiContext, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(key_guide, "open_link", opened.append)
    dialog = KeyGuideDialog(gui)
    button = dialog.steps[0].open_button
    assert button is not None
    button.click()
    assert opened == [SITE_URL]


def test_the_guide_follows_the_language(gui: GuiContext, kit: UiKit) -> None:
    dialog = KeyGuideDialog(gui)
    before = dialog.steps[1]._body.text()
    kit.language.set_language("ru")
    assert dialog.steps[1]._body.text() != before
    assert dialog._close.text() == tr("common.close")


def test_close_accepts(gui: GuiContext) -> None:
    dialog = KeyGuideDialog(gui)
    dialog.show()
    dialog._close.click()
    assert not dialog.isVisible()
    assert dialog.result() == 1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_scheme_paints(kit: UiKit, kind: str, theme: str) -> None:
    kit.theme.set_preference(theme)  # type: ignore[arg-type]
    art = SchemeArt(kit, kind)
    image = art.grab().toImage()
    assert not image.isNull()
    assert image.width() == art.width()
    kit.theme.set_preference("system")


def test_a_scheme_follows_the_zoom(kit: UiKit) -> None:
    art = SchemeArt(kit, "site")
    before = art.width()
    kit.zoom.set_factor(kit.zoom.factor * 1.25)
    assert art.width() > before


def test_an_unknown_scheme_is_refused(kit: UiKit) -> None:
    with pytest.raises(ValueError, match="unknown scheme"):
        SchemeArt(kit, "nope")
