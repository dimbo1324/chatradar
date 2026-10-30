"""The system tray: a thin menu over `ChatImportApp.execute` (spec §9.2).

pystray owns the main thread; the service runs on its own asyncio loop in a background thread.
Menu items only forward a command and show its failure; they hold no business logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import pystray
from PIL import Image, ImageDraw

from chatimport.control import AlreadyRunning
from chatimport.paths import normalize_root
from chatimport.runtime import Level
from chatimport.status import STATUS_FILE, format_status_lines

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from concurrent.futures import Future
    from pathlib import Path

    from chatimport.app import ChatImportApp, ServiceContext
    from chatimport.control import CommandResult

log = logging.getLogger(__name__)

type IconState = Literal["running", "paused", "error"]

REFRESH_SECONDS = 15.0
SERVICE_JOIN_SECONDS = 30.0
ALREADY_RUNNING_LINGER_SECONDS = 4.0
TOOLTIP_LIMIT = 127
ICON_SIZE = 64
STATE_COLORS: dict[str, tuple[int, int, int, int]] = {
    "running": (46, 160, 67, 255),
    "paused": (128, 128, 128, 255),
    "error": (200, 48, 48, 255),
}
TRIM_PERCENTS = (25, 50, 75)
LEVEL_PREFIX = {Level.INFO: "", Level.WARNING: "Warning: ", Level.ERROR: "Error: "}
LOG_LEVEL = {Level.INFO: logging.INFO, Level.WARNING: logging.WARNING, Level.ERROR: logging.ERROR}


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
        log.log(LOG_LEVEL[level], "%s: %s", full_title, message)
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


@contextmanager
def _tk_root() -> Generator[Any]:
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # pyright: ignore[reportUnknownMemberType]
    try:
        yield root
    finally:
        root.destroy()


def _confirm(title: str, question: str) -> bool:
    from tkinter import messagebox

    with _tk_root() as root:
        return bool(messagebox.askyesno(title, question, parent=root))


def _choose_folder() -> str:
    from tkinter import filedialog

    with _tk_root() as root:
        return str(filedialog.askdirectory(title="Choose the ChatImport folder", parent=root))


def _ask_move() -> bool | None:
    from tkinter import messagebox

    with _tk_root() as root:
        answer = messagebox.askyesnocancel(
            "Change folder",
            "Move the downloaded data to the new folder?\n\n"
            "Yes: move it.\nNo: leave the old data where it is and start fresh.\n"
            "Cancel: keep the current folder.",
            parent=root,
        )
        return None if answer is None else bool(answer)


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opens the user's own file with its default app
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path)])  # noqa: S603 - fixed argv, no shell


def _latest_file(folder: Path) -> Path | None:
    try:
        files = [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return None
    return max(files, key=_modified, default=None)


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("-inf")


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
        icon_class: Any = pystray.Icon
        self._icon: _TrayIcon = icon_class(
            "chatimport", make_icon_image("running"), "ChatImport", self._build_menu()
        )
        self._service = threading.Thread(target=self._serve, name="chatimport-service")

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

    def _read_status(self) -> dict[str, Any] | None:
        try:
            value: object = json.loads((self._root / STATUS_FILE).read_text(encoding="utf-8"))
        except OSError, ValueError:
            return None
        return cast("dict[str, Any]", value) if isinstance(value, dict) else None

    def _status_item_text(self, _item: object) -> str:
        return self._status_text()

    def _toggle_text(self, _item: object) -> str:
        return "Resume" if self._paused else "Pause"

    def _status_text(self) -> str:
        data = self._read_status()
        if data is None:
            return "ChatImport · starting"
        return " | ".join(format_status_lines(data))[:TOOLTIP_LIMIT]

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
            self._icon.update_menu()
        except Exception:
            log.exception("tray refresh failed")

    def _refresh_loop(self) -> None:
        while not self._stop_refresh.wait(REFRESH_SECONDS):
            self._refresh()

    def _open_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        _open_path(self._root)

    def _open_library(self) -> None:
        library = self._ctx.library_file
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
    _Tray(ctx).run()
