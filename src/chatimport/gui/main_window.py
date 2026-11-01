"""`MainWindow`: sidebar, top bar, page stack, status bar and toasts, wired to the service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from PySide6.QtCore import QRect, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chatimport import __version__
from chatimport.gui.i18n import plural, register_strings, tr
from chatimport.gui.locales import shell as shell_strings
from chatimport.gui.pages import PAGE_KEYS
from chatimport.gui.settings import WindowGeometry
from chatimport.gui.shell_state import chats_of, service_state
from chatimport.gui.shell_widgets import DownloadIndicator, ServiceChip
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.sidebar import NavEntry, NavSection, Sidebar
from chatimport.gui.widgets.status_bar import StatusBar
from chatimport.gui.widgets.toast import ToastHost
from chatimport.gui.widgets.top_bar import TopBar
from chatimport.gui.zoom import install_zoom_inputs
from chatimport.runtime import Level

if TYPE_CHECKING:
    from concurrent.futures import Future

    from chatimport.commands import CommandResult
    from chatimport.gui.context import GuiContext
    from chatimport.gui.notifier import QtNotifier
    from chatimport.gui.tray import QtTray
    from chatimport.gui.widgets.base import Tone

log = logging.getLogger(__name__)

register_strings("shell", shell_strings.EN, shell_strings.RU)

MIN_SIZE: Final = (960, 620)
DEFAULT_SIZE: Final = (1180, 760)
RESTORABLE_PAGES: Final = ("overview", "chats")
LEVEL_TONES: Final[dict[Level, Tone]] = {
    Level.INFO: "info",
    Level.WARNING: "warning",
    Level.ERROR: "danger",
}
SECTIONS: Final = (
    NavSection(
        "nav.section.archive",
        (
            NavEntry("overview", "nav.overview", "home"),
            NavEntry("chats", "nav.chats", "chats"),
        ),
    ),
    NavSection(
        "nav.section.system",
        (
            NavEntry("log", "nav.log", "log"),
            NavEntry("data", "nav.data", "data"),
            NavEntry("settings", "nav.settings", "settings"),
        ),
    ),
)


class MainWindow(QMainWindow):
    quit_requested = Signal()
    _command_done = Signal(bool)

    def __init__(
        self,
        gui: GuiContext,
        pages: dict[str, QWidget],
        notifier: QtNotifier,
        *,
        tray: QtTray | None = None,
    ) -> None:
        super().__init__()
        self.gui = gui
        self.kit = gui.kit
        self._pages = pages
        self._tray = tray
        self._quitting = False
        self._hint_shown = False
        self._current = ""
        self._failed_type: str | None = None
        self._command_done.connect(self._on_command_done)
        self.setMinimumSize(*MIN_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build()
        self._wire(notifier)
        self._restore_geometry()
        self._retitle()
        self._retranslate_banner()
        start = gui.settings.settings.last_page
        self.show_page(start if start in RESTORABLE_PAGES else "overview")
        snapshot = gui.bridge.last_snapshot
        if snapshot is not None:
            self._on_snapshot(snapshot)

    @property
    def current_page(self) -> str:
        return self._current

    @property
    def toasts(self) -> ToastHost:
        return self._toasts

    @property
    def sidebar(self) -> Sidebar:
        return self._sidebar

    @property
    def service_chip(self) -> ServiceChip:
        return self._chip

    @property
    def download_indicator(self) -> DownloadIndicator:
        return self._download

    def _build(self) -> None:
        settings = self.gui.settings.settings
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        self._sidebar = Sidebar(
            self.kit, SECTIONS, current="overview", collapsed=settings.sidebar_collapsed
        )
        right = QVBoxLayout()
        right.setSpacing(0)
        self._top = TopBar(self.kit)
        self._setup_button = Button(self.kit, variant="primary")
        self._setup_button.clicked.connect(self.open_telegram_setup)
        self._banner = Callout(self.kit, "warning", "", action=self._setup_button)
        self._banner.hide()
        self._stack = QStackedWidget()
        for key in PAGE_KEYS:
            self._stack.addWidget(self._pages[key])
        right.addWidget(self._top)
        right.addWidget(self._banner)
        right.addWidget(self._stack, 1)
        body.addWidget(self._sidebar)
        body.addLayout(right, 1)
        self._status = StatusBar(self.kit, __version__)
        self._chip = ServiceChip(self.kit)
        self._download = DownloadIndicator(self.kit)
        self._status.add_item(self._download)
        self._status.add_item(self._chip)
        outer.addLayout(body, 1)
        outer.addWidget(self._status)
        self.setCentralWidget(central)
        self._toasts = ToastHost(self.kit, self)

    def _wire(self, notifier: QtNotifier) -> None:
        self._sidebar.navigate.connect(self.show_page)
        self._sidebar.locked.connect(self._on_locked)
        self._sidebar.collapsed_changed.connect(self._on_collapsed)
        self.gui.bridge.snapshot.connect(self._on_snapshot)
        notifier.delivered.connect(self._on_note)
        self.kit.language.changed.connect(self._retitle)
        self.kit.language.changed.connect(self._retranslate_banner)
        install_zoom_inputs(self.kit.zoom, self)
        for index, key in enumerate(PAGE_KEYS, start=1):
            self._bind(f"Ctrl+{index}", lambda key=key: self._shortcut_page(key))
        self._bind("Ctrl+F", self._focus_search)
        self._bind("Ctrl+Q", self.request_quit)

    def _bind(self, sequence: str, action: Any) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(action)

    def attach_tray(self, tray: QtTray) -> None:
        self._tray = tray
        self._sync_tray(self.gui.bridge.last_snapshot)

    def show_page(self, key: str) -> None:
        if key not in self._pages:
            return
        self._current = key
        self._stack.setCurrentWidget(self._pages[key])
        self._sidebar.set_current(key)
        self._retitle()
        if key in RESTORABLE_PAGES:
            self.gui.settings.update(last_page=key)

    def show_window(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def run_command(self, command: str, args: dict[str, Any] | None = None) -> None:
        """Send a command to the service; a failure becomes a toast without raw error text."""
        future = self.gui.bridge.execute(command, args)

        def done(finished: Future[CommandResult]) -> None:
            try:
                ok = finished.result().ok
            except Exception:
                log.exception("command %s failed", command)
                ok = False
            self._command_done.emit(ok)

        future.add_done_callback(done)

    def toggle_pause(self) -> None:
        chats = chats_of(self.gui.bridge.last_snapshot)
        paused = bool(chats) and all(bool(c.get("paused")) for c in chats)
        self.run_command("resume" if paused else "pause")

    @Slot(bool)
    def _on_command_done(self, ok: bool) -> None:
        if not ok:
            self._toasts.push("danger", tr("shell.notice.command_failed"))

    def _shortcut_page(self, key: str) -> None:
        self.show_page(key)

    def open_telegram_setup(self) -> None:
        self.show_page("settings")
        show_section = getattr(self._pages["settings"], "show_section", None)
        if callable(show_section):
            show_section("telegram")

    def _retranslate_banner(self) -> None:
        self._banner.set_title(tr("shell.banner.title"))
        self._banner.set_body(tr("shell.banner.text"))
        self._setup_button.setText(tr("shell.banner.action"))

    def _focus_search(self) -> None:
        hook = getattr(self._pages[self._current], "focus_search", None)
        if callable(hook):
            hook()

    def _retitle(self) -> None:
        page = self._pages.get(self._current)
        title_key = getattr(page, "title_key", f"nav.{self._current}")
        subtitle_key = getattr(page, "subtitle_key", "")
        self._top.set_title(tr(title_key) if title_key else "")
        self._top.set_subtitle(tr(subtitle_key) if subtitle_key else "")
        self.setWindowTitle(tr("app.title"))

    def _on_locked(self, _key: str, reason: str) -> None:
        self._toasts.push("info", reason)

    def _on_collapsed(self, collapsed: bool) -> None:
        self.gui.settings.update(sidebar_collapsed=collapsed)

    def _on_note(self, level: Level, title: str, message: str) -> None:
        tone = LEVEL_TONES[level]
        if self._tray is not None and level != Level.INFO and not self.isVisible():
            self._tray.show_message(level, title, message)
        self._toasts.push(tone, message, title=title)

    def _on_snapshot(self, snapshot: dict[str, Any]) -> None:
        chats = chats_of(snapshot)
        self._banner.setVisible(snapshot.get("service") == "needs_setup")
        self._sidebar.set_badge("chats", str(len(chats)) if chats else None)
        self._chip.update_from(snapshot, self._failed_type is not None)
        self._download.update_from(snapshot)
        self._sync_tray(snapshot)

    def note_failure(self, kind: str) -> None:
        """The service thread ended with an error of type `kind` (never its message)."""
        self._failed_type = kind
        self._chip.update_from(self.gui.bridge.last_snapshot, True)
        self._toasts.push("danger", tr("shell.notice.failed", kind=kind))
        self._sync_tray(self.gui.bridge.last_snapshot)

    def _sync_tray(self, snapshot: dict[str, Any] | None) -> None:
        if self._tray is None:
            return
        state = service_state(snapshot, self._failed_type is not None)
        errors = bool((snapshot or {}).get("errors"))
        tray_state = "error" if state == "failed" or errors else "running"
        if state in ("paused", "stopped", "stopping"):
            tray_state = "paused"
        text = tr(f"shell.state.{state}")
        chats = len(chats_of(snapshot))
        if chats:
            text = f"{text} - {plural(chats, 'count.chats')}"
        self._tray.set_status(tray_state, text, paused=state == "paused")  # pyright: ignore[reportArgumentType]

    def _restore_geometry(self) -> None:
        saved = self.gui.settings.settings.geometry
        if saved is None or not self._on_screen(saved):
            self.resize(*DEFAULT_SIZE)
            return
        self.setGeometry(saved.x, saved.y, saved.width, saved.height)
        if saved.maximized:
            self.setWindowState(Qt.WindowState.WindowMaximized)

    @staticmethod
    def _on_screen(saved: WindowGeometry) -> bool:
        center = QRect(saved.x, saved.y, saved.width, saved.height).center()
        return QGuiApplication.screenAt(center) is not None

    def _save_geometry(self) -> None:
        maximized = self.isMaximized()
        rect = self.normalGeometry() if maximized else self.geometry()
        self.gui.settings.update(
            geometry=WindowGeometry(rect.x(), rect.y(), rect.width(), rect.height(), maximized)
        )

    def request_quit(self) -> None:
        """The real exit (tray menu, Ctrl+Q): remember the layout and leave the event loop."""
        if self._quitting:
            return
        self._quitting = True
        self._save_geometry()
        self.hide()
        self.quit_requested.emit()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        keep = (
            not self._quitting
            and self.gui.settings.settings.close_to_tray
            and self._tray is not None
            and self._tray.visible
        )
        if keep:
            self._save_geometry()
            event.ignore()
            self.hide()
            if not self._hint_shown and self._tray is not None:
                self._hint_shown = True
                self._tray.show_message(Level.INFO, tr("app.title"), tr("shell.tray.hidden"))
            return
        event.accept()
        self.request_quit()
