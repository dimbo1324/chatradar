# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

import pytest
import shiboken6
from PySide6.QtCore import QObject
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

from chatimport.commands import CommandResult
from chatimport.gui.main_window import MainWindow
from chatimport.gui.notifier import QtNotifier
from chatimport.gui.pages import PAGE_KEYS
from chatimport.gui.settings import WindowGeometry
from chatimport.runtime import Level

if TYPE_CHECKING:
    from collections.abc import Iterator

    from chatimport.gui.context import GuiContext
    from tests.unit.gui.conftest import FakeBridge


class StubPage(QWidget):
    def __init__(self, title_key: str = "", subtitle_key: str = "") -> None:
        super().__init__()
        self.title_key = title_key
        self.subtitle_key = subtitle_key
        self.searched = 0
        self.sections: list[str] = []

    def focus_search(self) -> None:
        self.searched += 1

    def show_section(self, name: str) -> None:
        self.sections.append(name)


class FakeTray(QObject):
    def __init__(self, visible: bool = False) -> None:
        super().__init__()
        self.visible = visible
        self.statuses: list[tuple[str, str, bool]] = []
        self.messages: list[tuple[Level, str, str]] = []

    def set_status(self, state: str, text: str, *, paused: bool) -> None:
        self.statuses.append((state, text, paused))

    def show_message(self, level: Level, title: str, message: str) -> None:
        self.messages.append((level, title, message))


def make_pages() -> dict[str, QWidget]:
    pages: dict[str, QWidget] = {key: StubPage() for key in PAGE_KEYS}
    pages["chats"] = StubPage("nav.chats", "")
    pages["log"] = QWidget()
    return pages


@pytest.fixture(autouse=True)
def windows(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[MainWindow]]:
    created: list[MainWindow] = []
    original = MainWindow.__init__

    def tracking(self: MainWindow, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(MainWindow, "__init__", tracking)
    yield created
    for item in created:
        item.hide()
        shiboken6.delete(item)
    qapp.processEvents()


@pytest.fixture
def window(gui: GuiContext, qapp: QApplication) -> MainWindow:
    return MainWindow(gui, make_pages(), QtNotifier())


def test_defaults_and_properties(window: MainWindow) -> None:
    assert window.current_page == "overview"
    assert window.toasts is window._toasts
    assert window.sidebar is window._sidebar
    assert window.service_chip is window._chip
    assert window.download_indicator is window._download
    assert window.minimumWidth() == 960
    assert window.size().width() == 1180


def test_restores_page_geometry_and_snapshot(
    gui: GuiContext, bridge: FakeBridge, qapp: QApplication
) -> None:
    gui.settings.update(
        last_page="chats", geometry=WindowGeometry(20, 20, 1000, 700, maximized=True)
    )
    bridge.last_snapshot = {"service": "needs_setup", "chats": [{"chat_id": 1}]}
    window = MainWindow(gui, make_pages(), QtNotifier())
    assert window.current_page == "chats"
    assert not window._banner.isHidden()
    assert window.isMaximized() or window.windowState()
    plain = WindowGeometry(20, 20, 1000, 700)
    gui.settings.update(last_page="log", geometry=plain)
    again = MainWindow(gui, make_pages(), QtNotifier())
    assert again.current_page == "overview"
    off = WindowGeometry(-90000, -90000, 400, 300)
    gui.settings.update(geometry=off)
    third = MainWindow(gui, make_pages(), QtNotifier())
    assert third.width() == 1180


def test_show_page_and_titles(window: MainWindow, gui: GuiContext) -> None:
    window.show_page("unknown")
    assert window.current_page == "overview"
    window.show_page("chats")
    assert gui.settings.settings.last_page == "chats"
    window.show_page("log")
    assert gui.settings.settings.last_page == "chats"
    window.show_page("data")
    window._sidebar.navigate.emit("overview")
    assert window.current_page == "overview"
    window._shortcut_page("settings")
    assert window.current_page == "settings"
    gui.language.set_language("ru")


def test_open_telegram_setup_and_search(window: MainWindow) -> None:
    window.open_telegram_setup()
    settings = window._pages["settings"]
    assert isinstance(settings, StubPage)
    assert settings.sections == ["telegram"]
    window._focus_search()
    assert settings.searched == 1
    window.show_page("log")
    window.open_telegram_setup()
    window.show_page("log")
    window._focus_search()


def test_open_telegram_setup_without_hook(gui: GuiContext, qapp: QApplication) -> None:
    pages = make_pages()
    pages["settings"] = QWidget()
    window = MainWindow(gui, pages, QtNotifier())
    window.open_telegram_setup()
    assert window.current_page == "settings"


def test_show_window_clears_minimized(window: MainWindow) -> None:
    window.showMinimized()
    window.show_window()
    assert window.isVisible()
    window.hide()


def test_run_command_outcomes(window: MainWindow, bridge: FakeBridge, qapp: QApplication) -> None:
    window.run_command("pause")
    assert bridge.calls[-1] == ("pause", {})
    assert window.toasts.count == 0
    bridge.replies["recheck"] = CommandResult(False, "no")
    window.run_command("recheck", {"days": 1})
    assert window.toasts.count == 1

    def raising(command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    bridge.execute = raising  # type: ignore[method-assign]
    window.run_command("pause")
    assert window.toasts.count == 2


def test_toggle_pause(window: MainWindow, bridge: FakeBridge) -> None:
    window.toggle_pause()
    assert bridge.calls[-1][0] == "pause"
    bridge.last_snapshot = {"service": "running", "chats": [{"paused": True}]}
    window.toggle_pause()
    assert bridge.calls[-1][0] == "resume"
    bridge.last_snapshot = {"service": "running", "chats": [{"paused": True}, {}]}
    window.toggle_pause()
    assert bridge.calls[-1][0] == "pause"


def test_sidebar_signals(window: MainWindow, gui: GuiContext) -> None:
    window._sidebar.locked.emit("data", "Soon")
    assert window.toasts.count == 1
    window._sidebar.set_collapsed(True, animate=False)
    assert gui.settings.settings.sidebar_collapsed is True


def test_snapshots_update_shell(window: MainWindow, bridge: FakeBridge) -> None:
    bridge.snapshot.emit(
        {"service": "needs_setup", "chats": [{"chat_id": 1}, {"chat_id": 2}], "errors": []}
    )
    assert not window._banner.isHidden()
    assert window.service_chip.state == "needs_setup"
    bridge.snapshot.emit({"service": "running", "chats": []})
    assert window._banner.isHidden()


def test_notes_route_to_toasts_and_tray(window: MainWindow) -> None:
    tray = FakeTray()
    window.attach_tray(tray)  # type: ignore[arg-type]
    assert tray.statuses
    window._on_note(Level.INFO, "T", "M")
    window._on_note(Level.WARNING, "T", "M")
    window._on_note(Level.ERROR, "T", "M")
    assert [m[0] for m in tray.messages] == [Level.WARNING, Level.ERROR]
    assert window.toasts.count == 3
    window.show()
    window._on_note(Level.ERROR, "T", "M")
    assert len(tray.messages) == 2
    window.hide()
    bare = window
    bare._tray = None
    bare._on_note(Level.ERROR, "T", "M")


def test_note_failure_and_tray_states(window: MainWindow, bridge: FakeBridge) -> None:
    tray = FakeTray()
    window.attach_tray(tray)  # type: ignore[arg-type]
    window.note_failure("RuntimeError")
    assert tray.statuses[-1][0] == "error"
    assert window.service_chip.state == "failed"
    window._failed_type = None
    window._sync_tray({"service": "running", "chats": [{"chat_id": 1}], "errors": ["x"]})
    assert tray.statuses[-1][0] == "error"
    window._sync_tray({"service": "running", "chats": [{"paused": True}]})
    assert tray.statuses[-1][0] == "paused"
    assert tray.statuses[-1][2] is True
    window._sync_tray({"service": "stopped"})
    assert tray.statuses[-1][0] == "paused"
    window._sync_tray({"service": "running", "chats": [{}]})
    assert tray.statuses[-1][0] == "running"
    window._sync_tray(None)
    window._tray = None
    window._sync_tray(None)


def test_request_quit_saves_layout_once(
    window: MainWindow, gui: GuiContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    quits: list[bool] = []
    window.quit_requested.connect(lambda: quits.append(True))
    ticks: list[bool] = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: ticks.append(True)))
    monkeypatch.setattr(MainWindow, "isMaximized", lambda self: True)
    window.request_quit()
    window.request_quit()
    assert quits == [True]
    assert ticks == [True]
    assert gui.settings.settings.geometry is not None
    assert gui.settings.settings.geometry.maximized


def test_request_quit_without_application(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    window.request_quit()
    assert window._quitting


def test_close_event_hides_to_tray_once(window: MainWindow, gui: GuiContext) -> None:
    tray = FakeTray(visible=True)
    window.attach_tray(tray)  # type: ignore[arg-type]
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert len(tray.messages) == 1
    again = QCloseEvent()
    window.closeEvent(again)
    assert not again.isAccepted()
    assert len(tray.messages) == 1


@pytest.mark.parametrize("variant", ["no_tray", "tray_hidden", "setting_off"])
def test_close_event_quits_otherwise(
    window: MainWindow, gui: GuiContext, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: None))
    if variant == "tray_hidden":
        window.attach_tray(FakeTray(visible=False))  # type: ignore[arg-type]
    if variant == "setting_off":
        window.attach_tray(FakeTray(visible=True))  # type: ignore[arg-type]
        gui.settings.update(close_to_tray=False)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert window._quitting
