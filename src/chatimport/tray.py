"""The system tray: a thin menu over `ChatImportApp.execute` (spec §9.2).

pystray owns the main thread; the service runs on its own asyncio loop in a background thread.
Menu items only forward a command and show its failure; they hold no business logic.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

from PIL import Image, ImageDraw

from chatimport.control import AlreadyRunning
from chatimport.logging_setup import configure_logging
from chatimport.paths import cloud_sync_warning, normalize_root
from chatimport.ports import ChatImportError
from chatimport.runtime import Level
from chatimport.status import format_status_lines, read_snapshot
from chatimport.tray_dialogs import ask_move as _ask_move
from chatimport.tray_dialogs import choose_folder as _choose_folder
from chatimport.tray_dialogs import confirm as _confirm
from chatimport.tray_dialogs import latest_file as _latest_file
from chatimport.tray_dialogs import open_path as _open_path
from chatimport.trim import ALLOWED_PERCENTS

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future
    from pathlib import Path

    from chatimport.app import ChatImportApp, ServiceContext
    from chatimport.control import CommandResult

log = logging.getLogger(__name__)


def _load_pystray() -> Any:
    """pystray raises on import without a display (headless Linux): treat that as no tray."""
    try:
        import pystray
    except Exception:
        log.info("pystray is not usable here; the tray is unavailable")
        return None
    return pystray


pystray: Any = _load_pystray()

type IconState = Literal["running", "paused", "error"]

REFRESH_SECONDS = 15.0
SERVICE_JOIN_SECONDS = 30.0
ALREADY_RUNNING_LINGER_SECONDS = 4.0
TOOLTIP_LIMIT: Final = 127
"""In UTF-16 code units: Windows keeps the tooltip in a 128-unit wide-char buffer."""
ICON_SIZE = 64
LIBRARY_SUFFIX: Final = ".toml"
STATE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "running": (46, 160, 67, 255),
    "paused": (128, 128, 128, 255),
    "error": (200, 48, 48, 255),
}
TRIM_PERCENTS: Final = ALLOWED_PERCENTS
LEVEL_PREFIX = {Level.INFO: "", Level.WARNING: "Warning: ", Level.ERROR: "Error: "}


class _TrayIcon(Protocol):
    """The slice of `pystray.Icon` used here; the library is loosely typed."""

    visible: bool
    icon: Image.Image
    title: str

    def run(self, setup: Callable[[_TrayIcon], None] | None = None) -> None: ...

    def stop(self) -> None: ...

    def notify(self, message: str, title: str | None = None) -> None: ...

    def update_menu(self) -> None: ...


def make_icon_image(state: str) -> Image.Image:
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    color = STATE_COLORS.get(state, STATE_COLORS["paused"])
    ImageDraw.Draw(image).ellipse((6, 6, ICON_SIZE - 6, ICON_SIZE - 6), fill=color)
    return image


class TrayNotifier:
    """Toasts through the tray icon; before the icon is visible they are queued."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._icon: _TrayIcon | None = None
        self._pending: list[tuple[str, str]] = []

    def attach(self, icon: _TrayIcon) -> None:
        with self._lock:
            self._icon = icon
            pending, self._pending = self._pending, []
        for title, message in pending:
            self._toast(icon, title, message)

    def detach(self) -> None:
        with self._lock:
            self._icon = None

    def notify(self, level: Level, title: str, message: str) -> None:
        full_title = LEVEL_PREFIX[level] + title
        log.log(level.logging_level, "%s: %s", full_title, message)
        with self._lock:
            icon = self._icon
            if icon is None:
                self._pending.append((full_title, message))
                return
        self._toast(icon, full_title, message)

    @staticmethod
    def _toast(icon: _TrayIcon, title: str, message: str) -> None:
        try:
            icon.notify(message, title)
        except Exception:
            log.exception("tray notification failed")


def fit_utf16(text: str, limit: int = TOOLTIP_LIMIT) -> str:
    """The longest prefix of `text` within `limit` UTF-16 units; an emoji (two units) is never
    split in half."""
    used = 0
    for index, char in enumerate(text):
        used += 2 if ord(char) > 0xFFFF else 1
        if used > limit:
            return text[:index]
    return text


class _Tray:
    def __init__(self, ctx: ServiceContext) -> None:
        from chatimport.app import ChatImportApp

        self._ctx = ctx
        self._root = ctx.root
        self._notifier = TrayNotifier()
        self._app: ChatImportApp = ChatImportApp(ctx, notifier=self._notifier)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._icon_ready = threading.Event()
        self._stop_refresh = threading.Event()
        self._closing = threading.Lock()
        self._closed = False
        self._paused = False
        self._failed = False
        self._state: IconState = "running"
        if pystray is None:
            raise ChatImportError("the system tray is not available on this machine")
        icon_class: Any = pystray.Icon
        self._icon: _TrayIcon = icon_class(
            "chatimport", make_icon_image("running"), "ChatImport", self._build_menu()
        )
        self._service = threading.Thread(target=self._serve, name="chatimport-service")
        self._warn_if_cloud_synced(self._root)

    def run(self) -> None:
        self._service.start()
        threading.Thread(
            target=self._refresh_loop, name="chatimport-tray-refresh", daemon=True
        ).start()
        try:
            self._icon.run(setup=self._on_ready)
        finally:
            self._shutdown()

    def _on_ready(self, icon: _TrayIcon) -> None:
        icon.visible = True
        self._notifier.attach(icon)
        self._icon_ready.set()
        self._refresh()

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_until_complete(self._app.run())
        except AlreadyRunning:
            self._icon_ready.wait(10.0)
            self._notifier.notify(Level.INFO, "ChatImport", "ChatImport is already running")
            self._stop_refresh.wait(ALREADY_RUNNING_LINGER_SECONDS)
            self._icon.stop()
        except Exception as exc:
            log.exception("the ChatImport service stopped")
            self._failed = True
            self._icon_ready.wait(10.0)
            self._notifier.notify(
                Level.ERROR, "ChatImport stopped", f"The service failed: {type(exc).__name__}"
            )
            self._refresh()
        else:
            self._icon.stop()
        finally:
            loop.close()

    def _shutdown(self) -> None:
        with self._closing:
            if self._closed:
                return
            self._closed = True
        self._stop_refresh.set()
        self._app.request_shutdown()
        self._service.join(SERVICE_JOIN_SECONDS)
        if self._service.is_alive():
            log.warning("the service thread did not stop within %s s", SERVICE_JOIN_SECONDS)
        self._notifier.detach()

    def _exit(self) -> None:
        self._shutdown()
        self._icon.stop()

    def _submit(
        self, command: str, args: dict[str, Any], *, success_message: str | None = None
    ) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            self._notifier.notify(Level.ERROR, "ChatImport", "The service is not running")
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._app.execute(command, args), loop)
        except RuntimeError:
            self._notifier.notify(Level.ERROR, "ChatImport", "The service is not running")
            return
        future.add_done_callback(lambda done: self._report(command, done, args, success_message))

    def _report(
        self,
        command: str,
        future: Future[CommandResult],
        args: dict[str, Any],
        success_message: str | None,
    ) -> None:
        try:
            result = future.result()
        except Exception as exc:
            log.exception("command %s failed", command)
            self._notifier.notify(
                Level.ERROR, "ChatImport", f"{command} failed: {type(exc).__name__}"
            )
            return
        if not result.ok:
            self._notifier.notify(Level.ERROR, "ChatImport", result.message or f"{command} failed")
            return
        if command == "pause":
            self._paused = True
        elif command == "resume":
            self._paused = False
        elif command == "set_root":
            self._root = normalize_root(str(args["path"]))
            self._warn_if_cloud_synced(self._root)
        if success_message:
            self._notifier.notify(Level.INFO, "ChatImport", result.message or success_message)
        self._refresh()

    def _in_thread(self, name: str, target: Any) -> None:
        threading.Thread(target=self._guarded, args=(name, target), daemon=True).start()

    @staticmethod
    def _guarded(name: str, target: Any) -> None:
        try:
            target()
        except Exception:
            log.exception("tray action %s failed", name)

    def _build_menu(self) -> Any:
        menu: Any = pystray.Menu
        item: Any = pystray.MenuItem
        trim_items = [
            item(f"{pct} %", lambda pct=pct: self._in_thread("trim", lambda: self._trim(pct)))
            for pct in TRIM_PERCENTS
        ]
        return menu(
            item(self._status_item_text, None, enabled=False),
            menu.SEPARATOR,
            item("Open ChatImport folder", lambda: self._in_thread("open", self._open_root)),
            item("Change folder…", lambda: self._in_thread("set_root", self._change_root)),
            item("Open chat library", lambda: self._in_thread("library", self._open_library)),
            menu.SEPARATOR,
            item(
                "Recheck edits now",
                lambda: self._submit("recheck", {}, success_message="Recheck started"),
            ),
            item("Clean up old messages", menu(*trim_items)),
            item(
                self._toggle_text,
                lambda: self._submit("resume" if self._paused else "pause", {}),
            ),
            item(
                "Reload config",
                lambda: self._submit("reload_config", {}, success_message="Config reloaded"),
            ),
            item("Open log", lambda: self._in_thread("log", self._open_log)),
            menu.SEPARATOR,
            item("Exit", lambda: self._in_thread("exit", self._exit)),
        )

    def _warn_if_cloud_synced(self, root: Path) -> None:
        warning = cloud_sync_warning(root)
        if warning is not None:
            self._notifier.notify(Level.WARNING, "ChatImport", warning)

    def _read_status(self) -> dict[str, Any] | None:
        return read_snapshot(self._root)

    def _status_item_text(self, _item: object) -> str:
        return self._status_text()

    def _toggle_text(self, _item: object) -> str:
        return "Resume" if self._paused else "Pause"

    def _status_text(self) -> str:
        data = self._read_status()
        if data is None:
            return "ChatImport · starting"
        return fit_utf16(" | ".join(format_status_lines(data)))

    def _current_state(self) -> IconState:
        data = self._read_status()
        if self._failed or (data is not None and data.get("errors")):
            return "error"
        if self._paused or (data is not None and data.get("service") not in (None, "running")):
            return "paused"
        return "running"

    def _refresh(self) -> None:
        state = self._current_state()
        try:
            if state != self._state:
                self._state = state
                self._icon.icon = make_icon_image(state)
            self._icon.title = self._status_text()
        except Exception:
            log.exception("tray refresh failed: icon")
        try:
            self._icon.update_menu()
        except Exception:
            log.exception("tray refresh failed: menu")

    def _refresh_loop(self) -> None:
        while not self._stop_refresh.wait(REFRESH_SECONDS):
            self._refresh()

    def _open_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        _open_path(self._root)

    def _open_library(self) -> None:
        library = self._ctx.library_file
        if library.suffix.lower() != LIBRARY_SUFFIX:
            self._notifier.notify(
                Level.WARNING, "ChatImport", f"The library must be a {LIBRARY_SUFFIX} file"
            )
            return
        if not library.exists():
            library.parent.mkdir(parents=True, exist_ok=True)
            library.touch()
        _open_path(library)

    def _open_log(self) -> None:
        latest = _latest_file(self._ctx.paths.log_dir)
        if latest is None:
            self._notifier.notify(Level.INFO, "ChatImport", "There is no log file yet")
            return
        _open_path(latest)

    def _trim(self, pct: int) -> None:
        question = f"Delete the oldest {pct} % of the downloaded messages? This cannot be undone."
        if _confirm("Clean up old messages", question):
            self._submit("trim", {"pct": pct, "chat": None}, success_message="Cleanup finished")

    def _change_root(self) -> None:
        chosen = _choose_folder()
        if not chosen:
            return
        move = _ask_move()
        if move is None:
            return
        self._submit("set_root", {"path": chosen, "move": move}, success_message="Folder changed")


def run_tray(ctx: ServiceContext) -> None:
    configure_logging(ctx.paths.log_dir, console=False)
    _Tray(ctx).run()
