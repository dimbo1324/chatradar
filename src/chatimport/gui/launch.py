"""`run_gui`: build the application, the service host and the window, and run the Qt loop."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from chatimport.assets import ICON_ICO
from chatimport.gui.context import GuiContext
from chatimport.gui.i18n import tr
from chatimport.gui.kit import build_kit
from chatimport.gui.main_window import MainWindow
from chatimport.gui.notifier import QtNotifier
from chatimport.gui.pages import build_pages
from chatimport.gui.service_host import AppFactory, ServiceHost, default_app_factory
from chatimport.gui.settings import GuiSettingsStore
from chatimport.gui.tray import QtTray
from chatimport.logging_setup import configure_logging
from chatimport.paths import cloud_sync_warning

if TYPE_CHECKING:
    from chatimport.context import ServiceContext

log = logging.getLogger(__name__)

APP_NAME: Final = "ChatImport"
APP_USER_MODEL_ID: Final = "ChatImport.Desktop"
SETTINGS_FILE: Final = "gui.json"
EXIT_ALREADY_RUNNING: Final = 1


def _set_app_user_model_id() -> None:
    if sys.platform == "win32":
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except AttributeError, OSError:
            log.warning("could not set the application user model id")


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    return QApplication(sys.argv[:1])


def run_gui(
    ctx: ServiceContext,
    *,
    start_hidden: bool = False,
    app_factory: AppFactory = default_app_factory,
) -> int:
    """Run the window together with the service until the owner quits; the exit code."""
    configure_logging(ctx.paths.log_dir, console=False)
    _set_app_user_model_id()
    app = _application()
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(ICON_ICO)))
    store = GuiSettingsStore(ctx.paths.base / SETTINGS_FILE)
    kit = build_kit(store, app)
    notifier = QtNotifier()
    host = ServiceHost(ctx, notifier, app_factory=app_factory)
    gui = GuiContext(
        service=ctx,
        theme=kit.theme,
        language=kit.language,
        zoom=kit.zoom,
        settings=store,
        bridge=host,  # pyright: ignore[reportArgumentType],
    )
    window = MainWindow(gui, build_pages(gui), notifier)
    tray = QtTray(kit)
    window.attach_tray(tray)
    outcome = {"code": 0}

    def on_already_running() -> None:
        outcome["code"] = EXIT_ALREADY_RUNNING
        window.hide()
        tray.hide()
        QMessageBox.warning(None, tr("shell.dialog.running_title"), tr("shell.dialog.running_text"))
        app.quit()

    host.already_running.connect(on_already_running)
    host.failed.connect(window.note_failure)
    tray.open_requested.connect(window.show_window)
    tray.toggle_pause_requested.connect(window.toggle_pause)
    tray.recheck_requested.connect(lambda: window.run_command("recheck"))
    tray.quit_requested.connect(window.request_quit)
    tray.show()
    host.start()
    if start_hidden or store.settings.start_hidden:
        if not tray.visible:
            window.show_window()
    else:
        window.show_window()
    warning = cloud_sync_warning(ctx.root)
    if warning is not None:
        QTimer.singleShot(0, lambda: window.toasts.push("warning", tr("shell.notice.cloud")))
    try:
        app.exec()
    finally:
        tray.hide()
        host.shutdown()
    return outcome["code"]
