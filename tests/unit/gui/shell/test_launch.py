# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import ctypes
import logging
from typing import TYPE_CHECKING, Any

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication, QMessageBox

from chatimport.gui import launch
from chatimport.gui.launch import EXIT_ALREADY_RUNNING, run_gui
from chatimport.gui.main_window import MainWindow
from chatimport.gui.service_host import ServiceHost
from chatimport.gui.settings import GuiSettingsStore
from chatimport.gui.tray import QtTray
from chatimport.logging_setup import configure_logging

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from chatimport.context import ServiceContext


class Captured:
    def __init__(self) -> None:
        self.host: ServiceHost | None = None
        self.window: MainWindow | None = None
        self.tray: QtTray | None = None
        self.tray_visible = False
        self.shown = 0
        self.warnings: list[str] = []
        self.exec_calls = 0


@pytest.fixture
def captured(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[Captured]:
    state = Captured()

    class SpyHost(ServiceHost):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            state.host = self

    class SpyWindow(MainWindow):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            state.window = self

        def show_window(self) -> None:
            state.shown += 1

    class SpyTray(QtTray):
        @property
        def visible(self) -> bool:
            return state.tray_visible

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            state.tray = self

    monkeypatch.setattr(launch, "ServiceHost", SpyHost)
    monkeypatch.setattr(launch, "MainWindow", SpyWindow)
    monkeypatch.setattr(launch, "QtTray", SpyTray)
    monkeypatch.setattr(launch, "_set_app_user_model_id", lambda: None)
    monkeypatch.setattr(launch, "cloud_sync_warning", lambda path: None)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: state.warnings.append(str(args[2]))),
    )
    yield state
    qapp.setQuitOnLastWindowClosed(True)
    configure_logging(None, console=False)
    if state.window is not None:
        shiboken6.delete(state.window)
    qapp.processEvents()


def set_exec(
    monkeypatch: pytest.MonkeyPatch, captured: Captured, action: Callable[[], None] | None = None
) -> None:
    def fake_exec(self: QApplication) -> int:
        captured.exec_calls += 1
        if action is not None:
            action()
        return 0

    monkeypatch.setattr(QApplication, "exec", fake_exec)


def test_run_gui_shows_window(
    service_context: ServiceContext, captured: Captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_exec(monkeypatch, captured)
    assert run_gui(service_context) == 0
    assert captured.exec_calls == 1
    assert captured.shown == 1
    assert captured.host is not None
    assert captured.host._closed
    assert QApplication.applicationName() == "ChatImport"


@pytest.mark.parametrize(
    ("argument", "stored", "tray_visible", "shown"),
    [
        (True, False, False, 1),
        (True, False, True, 0),
        (False, True, False, 1),
        (False, True, True, 0),
    ],
)
def test_run_gui_start_hidden_rules(
    service_context: ServiceContext,
    captured: Captured,
    monkeypatch: pytest.MonkeyPatch,
    argument: bool,
    stored: bool,
    tray_visible: bool,
    shown: int,
) -> None:
    GuiSettingsStore(service_context.paths.base / "gui.json").update(start_hidden=stored)
    captured.tray_visible = tray_visible
    set_exec(monkeypatch, captured)
    run_gui(service_context, start_hidden=argument)
    assert captured.shown == shown


def test_run_gui_tray_requests_and_failure(
    service_context: ServiceContext, captured: Captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    def act() -> None:
        assert captured.tray is not None
        assert captured.window is not None
        assert captured.host is not None
        captured.tray.open_requested.emit()
        captured.tray.toggle_pause_requested.emit()
        captured.tray.recheck_requested.emit()
        captured.host.failed.emit("RuntimeError")
        assert captured.window.service_chip.state == "failed"
        captured.tray.quit_requested.emit()
        assert captured.window._quitting

    set_exec(monkeypatch, captured, act)
    assert run_gui(service_context) == 0


def test_run_gui_already_running_exit_code(
    service_context: ServiceContext, captured: Captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    def act() -> None:
        assert captured.host is not None
        captured.host.already_running.emit()

    set_exec(monkeypatch, captured, act)
    assert run_gui(service_context) == EXIT_ALREADY_RUNNING
    assert len(captured.warnings) == 1


def test_run_gui_cloud_warning_toast(
    service_context: ServiceContext,
    captured: Captured,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launch, "cloud_sync_warning", lambda path: "synced")

    def act() -> None:
        qapp.processEvents()
        assert captured.window is not None
        assert captured.window.toasts.count == 1

    set_exec(monkeypatch, captured, act)
    run_gui(service_context)


def test_run_gui_shuts_the_host_down_when_exec_raises(
    service_context: ServiceContext, captured: Captured, monkeypatch: pytest.MonkeyPatch
) -> None:
    def act() -> None:
        raise RuntimeError("loop crashed")

    set_exec(monkeypatch, captured, act)
    with pytest.raises(RuntimeError, match="loop crashed"):
        run_gui(service_context)
    assert captured.host is not None
    assert captured.host._closed


def test_application_creates_one_when_missing(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    policies: list[object] = []

    class Missing:
        def __new__(cls, argv: list[str]) -> QApplication:
            return qapp

        @staticmethod
        def instance() -> None:
            return None

    monkeypatch.setattr(launch, "QApplication", Missing)
    monkeypatch.setattr(
        launch.QGuiApplication,
        "setHighDpiScaleFactorRoundingPolicy",
        staticmethod(policies.append),
    )
    assert launch._application() is qapp
    assert len(policies) == 1
    monkeypatch.undo()
    assert launch._application() is qapp


class FakeShell32:
    def __init__(self, error: BaseException | None) -> None:
        self.error = error
        self.ids: list[str] = []

    def SetCurrentProcessExplicitAppUserModelID(self, value: str) -> None:
        if self.error is not None:
            raise self.error
        self.ids.append(value)


class FakeWindll:
    def __init__(self, error: BaseException | None) -> None:
        self.shell32 = FakeShell32(error)


def test_app_user_model_id_paths(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ok = FakeWindll(None)
    monkeypatch.setattr(ctypes, "windll", ok, raising=False)
    monkeypatch.setattr(launch.sys, "platform", "win32")
    launch._set_app_user_model_id()
    assert ok.shell32.ids == [launch.APP_USER_MODEL_ID]
    for error in (AttributeError("x"), OSError("y")):
        monkeypatch.setattr(ctypes, "windll", FakeWindll(error), raising=False)
        with caplog.at_level(logging.WARNING, logger=launch.__name__):
            launch._set_app_user_model_id()
    assert caplog.text.count("could not set") == 2
    monkeypatch.setattr(launch.sys, "platform", "linux")
    launch._set_app_user_model_id()
    assert ok.shell32.ids == [launch.APP_USER_MODEL_ID]
