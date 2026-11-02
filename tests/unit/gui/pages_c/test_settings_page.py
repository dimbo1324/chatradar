from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QSpinBox

from chatimport.gui.context import GuiContext
from chatimport.gui.pages.settings import SettingsPage
from chatimport.gui.pages.settings_support import SettingsHooks
from chatimport.gui.widgets.toast import ToastHost
from tests.unit.gui.conftest import FakeBridge

if TYPE_CHECKING:
    from chatimport.context import ServiceContext
    from chatimport.gui.kit import UiKit
    from chatimport.gui.settings import GuiSettingsStore
    from tests.unit.gui.pages_c.conftest import FakeAutostart, FakeControl

HASH = "0123456789abcdef0123456789abcdef"


def hooks_of(control: FakeControl | None = None) -> SettingsHooks:
    return SettingsHooks(probe=lambda ctx: None, control=control)


def test_builds_every_card_with_default_hooks(gui: GuiContext) -> None:
    page = SettingsPage(gui)
    assert list(page.cards) == [
        "telegram",
        "collection",
        "recheck",
        "disk",
        "media",
        "privacy",
        "appearance",
        "startup",
        "about",
    ]
    assert page._control is None
    assert page._invalid.isHidden()
    assert page._restart_note.isHidden()


def test_reload_reports_an_invalid_config_and_keeps_edits(gui: GuiContext) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    config_file = gui.service.paths.config_file
    config_file.write_text("[live\n", encoding="utf-8")
    page.reload()
    assert not page._invalid.isHidden()

    config_file.write_text("[live]\nflush_every_messages = 11\n", encoding="utf-8")
    page.reload()
    assert page._invalid.isHidden()
    collection = page.cards["collection"]
    spin = collection._editors["live", "flush_every_messages"].widget  # type: ignore[attr-defined]
    assert isinstance(spin, QSpinBox)
    assert spin.value() == 11

    spin.setValue(12)
    page.telegram._api_id.setText("5")
    config_file.write_text("[live]\nflush_every_messages = 13\n", encoding="utf-8")
    page.reload()
    assert spin.value() == 12
    assert page.telegram._api_id.text() == "5"


def test_show_refreshes_the_dynamic_cards(gui: GuiContext, fake_autostart: FakeAutostart) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    page.show()
    assert fake_autostart.calls == ["status"]
    page.hide()


def test_navigation_scrolls_and_follows_the_scroll(gui: GuiContext) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    page.resize(1000, 500)
    page.show()
    QApplication.processEvents()
    page.show_section("nope")
    page.show_section("about")
    QApplication.processEvents()
    bar = page._scroll.verticalScrollBar()
    assert bar.value() > 0
    assert not page._nav_items["telegram"]._active
    assert sum(item._active for item in page._nav_items.values()) == 1
    bar.setValue(0)
    assert page._nav_items["telegram"]._active
    assert not page._nav_items["about"]._active
    page._nav_items["disk"].clicked.emit()
    QApplication.processEvents()
    assert page._nav_items["disk"]._active
    page.hide()


def test_language_and_zoom_changes_are_applied(gui: GuiContext, kit: UiKit) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    before = page._restart_button.text()
    kit.language.set_language("ru")
    assert page._restart_button.text() != before
    kit.zoom.set_factor(1.5)
    assert page._nav_box.width() == kit.px(200)


def test_saved_while_stopped_shows_a_toast(gui: GuiContext) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    toasts = ToastHost(gui.kit, page)
    page.cards["privacy"]._editors["output", "include_raw"].write(True)  # type: ignore[attr-defined]
    page.cards["privacy"].save()  # type: ignore[attr-defined]
    assert toasts.count == 1
    assert page._restart_note.isHidden()


def test_saved_while_running_offers_a_restart(
    control_gui: GuiContext, control: FakeControl, service_context: ServiceContext
) -> None:
    page = SettingsPage(control_gui, hooks=hooks_of())
    toasts = ToastHost(control_gui.kit, page)
    control.snapshot.emit({"service": "running"})
    page.cards["privacy"]._editors["output", "include_raw"].write(True)  # type: ignore[attr-defined]
    page.cards["privacy"].save()  # type: ignore[attr-defined]
    assert not page._restart_note.isHidden()

    page.telegram._api_id.setText("5")
    page.telegram._api_hash.setText(HASH)
    page.telegram.save()
    assert not page._restart_note.isHidden()

    page._restart_button.click()
    assert control.restarts == 1
    assert page._restart_note.isHidden()
    assert toasts.count == 1

    page._restart_note.show()
    control.snapshot.emit({"service": "running"})
    assert not page._restart_note.isHidden()
    control.snapshot.emit({"service": "stopped"})
    assert page._restart_note.isHidden()


def test_restart_without_control_only_hides_the_note(gui: GuiContext) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    page._restart_note.show()
    page._restart_service()
    assert page._restart_note.isHidden()


def test_running_without_control_still_toasts(gui: GuiContext, bridge: FakeBridge) -> None:
    page = SettingsPage(gui, hooks=hooks_of())
    toasts = ToastHost(gui.kit, page)
    bridge.snapshot.emit({"service": "running"})
    page._on_config_saved()
    assert toasts.count == 1
    assert page._restart_note.isHidden()


def test_last_snapshot_is_applied_at_construction(
    kit: UiKit,
    store: GuiSettingsStore,
    service_context: ServiceContext,
) -> None:
    bridge = FakeBridge({"service": "running"})
    gui = GuiContext(
        service=service_context,
        theme=kit.theme,
        language=kit.language,
        zoom=kit.zoom,
        settings=store,
        bridge=bridge,  # type: ignore[arg-type]
    )
    page = SettingsPage(gui, hooks=hooks_of())
    assert page._service == "running"
    assert page.telegram._service == "running"
