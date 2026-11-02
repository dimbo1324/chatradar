from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatimport.gui.format import DAY, FreshnessThresholds
from chatimport.gui.pages.settings_appearance import AppearanceCard, ThresholdEdit
from chatimport.gui.settings import GuiSettingsStore
from chatimport.gui.tokens import ZOOM_MIN

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit


@pytest.mark.parametrize(
    ("seconds", "unit", "number"),
    [(30, "s", 30), (120, "min", 2), (7200, "h", 2), (2 * DAY, "d", 2), (90, "s", 90), (0, "s", 1)],
)
def test_threshold_edit_picks_the_largest_exact_unit(
    kit: UiKit, seconds: int, unit: str, number: int
) -> None:
    edit = ThresholdEdit(kit)
    edit.set_seconds(seconds)
    assert edit.unit.currentData() == unit
    assert edit.spin.value() == number
    assert edit.seconds() == max(seconds, 1)


def test_threshold_edit_retranslate_keeps_the_unit(kit: UiKit) -> None:
    edit = ThresholdEdit(kit)
    edit.set_seconds(3600)
    edit.retranslate()
    assert edit.unit.currentData() == "h"


def test_theme_and_language_pickers(gui: GuiContext) -> None:
    card = AppearanceCard(gui)
    card._theme.choose(1)
    assert gui.kit.theme.preference == "dark"
    card._pick_theme("bogus")
    assert gui.kit.theme.preference == "dark"
    card._language.choose(1)
    assert gui.kit.language.current == "ru"
    card._pick_language("xx")
    assert gui.kit.language.current == "ru"


def test_zoom_controls(gui: GuiContext) -> None:
    card = AppearanceCard(gui)
    gui.kit.zoom.set_factor(1.0)
    assert "(" not in card._zoom_text.text()
    card._zoom_in.click()
    assert gui.kit.zoom.factor > 1.0
    card._zoom_out.click()
    card._zoom_auto.click()
    assert gui.kit.zoom.auto
    assert "(" in card._zoom_text.text()
    gui.kit.zoom.set_factor(ZOOM_MIN)
    assert not card._zoom_out.isEnabled()
    assert card._zoom_in.isEnabled()


def test_window_switches_write_the_store(gui: GuiContext, store: GuiSettingsStore) -> None:
    card = AppearanceCard(gui)
    card._tray.click()
    card._hidden.click()
    reloaded = GuiSettingsStore(store.path).settings
    assert reloaded.close_to_tray is False
    assert reloaded.start_hidden is True


def test_threshold_edits_persist_and_reset(gui: GuiContext, store: GuiSettingsStore) -> None:
    card = AppearanceCard(gui)
    card._apply_thresholds()
    assert not store.path.exists()
    fresh = card._edits["fresh_below"]
    fresh.set_seconds(60)
    card._apply_thresholds()
    assert GuiSettingsStore(store.path).settings.freshness.fresh_below == 60
    assert card.message.isHidden()
    card._reset.click()
    assert store.settings.freshness == FreshnessThresholds()
    assert card._edits["fresh_below"].seconds() == FreshnessThresholds().fresh_below


def test_unordered_thresholds_are_refused(gui: GuiContext, store: GuiSettingsStore) -> None:
    card = AppearanceCard(gui)
    stale = card._edits["stale_below"]
    stale.set_seconds(10)
    stale.spin.valueChanged.emit(10)
    assert not card.message.isHidden()
    assert store.settings.freshness == FreshnessThresholds()
    assert not store.path.exists()


def test_stored_thresholds_are_shown_and_language_retranslates(
    kit: UiKit, store: GuiSettingsStore, gui: GuiContext
) -> None:
    store.update(freshness=FreshnessThresholds(120, 7200, 3 * DAY))
    card = AppearanceCard(gui)
    assert card._edits["recent_below"].seconds() == 7200
    english = card._reset.text()
    kit.language.set_language("ru")
    assert card._reset.text() != english
