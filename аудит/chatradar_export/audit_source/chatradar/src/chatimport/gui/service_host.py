"""`ServiceHost`: the archive service on a background asyncio thread, seen from the Qt thread.

The window never touches the service directly. `execute` schedules a command on the service's
loop and returns a `concurrent.futures.Future`; every two seconds the host asks for `status`
and publishes the result as the `snapshot` signal. Whatever happens on the service thread
reaches Qt through an internal signal, so every public signal fires on the main thread.

The service can be stopped and started again (`stop_service`, `start_service`, `restart`): a
new `ChatImportApp` and thread per start, with the configuration reread from disk. Without
Telegram credentials or a session file the service is not started at all and the state is
`needs_setup`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final, cast

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from chatimport.config import ConfigError, load_config
from chatimport.control import AlreadyRunning
from chatimport.paths import library_path, resolve_root
from chatimport.ports import ChatImportError
from chatimport.status import read_snapshot

if TYPE_CHECKING:
    from collections.abc import Callable

    from chatimport.app import ChatImportApp
    from chatimport.commands import CommandResult
    from chatimport.context import ServiceContext
    from chatimport.runtime import Notifier

log = logging.getLogger(__name__)

POLL_MS: Final = 2000
JOIN_SECONDS: Final = 30.0
NOT_RUNNING: Final = "the service is not running"
NEEDS_SETUP: Final = "needs_setup"

type AppFactory = Callable[[ServiceContext, Notifier], ChatImportApp]


def default_app_factory(ctx: ServiceContext, notifier: Notifier) -> ChatImportApp:
    from chatimport.app import ChatImportApp

    return ChatImportApp(ctx, notifier=notifier)


def _failed_future(message: str) -> Future[CommandResult]:
    future: Future[CommandResult] = Future()
    future.set_exception(ChatImportError(message))
    return future


class ServiceHost(QObject):
    snapshot = Signal(dict)
    already_running = Signal()
    failed = Signal(str)
    stopped = Signal()

    _relay = Signal(str, object)

    def __init__(
        self,
        ctx: ServiceContext,
        notifier: Notifier,
        *,
        app_factory: AppFactory = default_app_factory,
        poll_ms: int = POLL_MS,
        root_override: str | None = None,
    ) -> None:
        super().__init__()
        self._ctx = ctx
        self._notifier = notifier
        self._factory = app_factory
        self._root_override = root_override
        self._app: ChatImportApp | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generation = 0
        self._last: dict[str, Any] | None = None
        self._failed_type: str | None = None
        self._polling = False
        self._closed = False
        self._relay.connect(self._on_relay)
        self._timer = QTimer(self)
        self._timer.setInterval(poll_ms)
        self._timer.timeout.connect(self._poll)

    @property
    def last_snapshot(self) -> dict[str, Any] | None:
        return self._last

    @property
    def failed_type(self) -> str | None:
        return self._failed_type

    @property
    def context(self) -> ServiceContext:
        return self._ctx

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def needs_setup(self) -> bool:
        """No credentials or no session file: the service cannot start yet."""
        telegram = self._ctx.config.telegram
        return not telegram.is_configured or not self._ctx.paths.session_file.is_file()

    def start(self) -> None:
        self._timer.start()
        if not self.start_service():
            self._publish(None)
        self._poll()

    def start_service(self) -> bool:
        """Start the service on a fresh thread with the configuration reread from disk.

        False when it is already running, the host is closed or Telegram is not set up.
        """
        if self._closed or self.is_alive:
            return False
        self._reload_context()
        if self.needs_setup:
            self._publish(None)
            return False
        self._failed_type = None
        self._generation += 1
        app = self._factory(self._ctx, self._notifier)
        self._app = app
        self._loop = None
        thread = threading.Thread(
            target=self._serve, args=(self._generation, app), name="chatimport-service"
        )
        self._thread = thread
        thread.start()
        return True

    def stop_service(self, on_stopped: Callable[[], None] | None = None) -> None:
        """Ask the service to stop; `on_stopped` runs on the main thread once its thread ended
        (at once when it was not running). The window stays responsive meanwhile."""
        app, thread = self._app, self._thread
        if app is None or thread is None or not thread.is_alive():
            if on_stopped is not None:
                on_stopped()
            return
        app.request_shutdown()
        generation = self._generation

        def join() -> None:
            thread.join(JOIN_SECONDS)
            self._relay.emit("joined", (generation, on_stopped))

        threading.Thread(target=join, name="chatimport-service-join", daemon=True).start()

    def restart(self) -> None:
        def start() -> None:
            self.start_service()

        self.stop_service(start)

    def execute(self, command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        loop, app = self._loop, self._app
        if app is None or loop is None or loop.is_closed() or not self.is_alive:
            return _failed_future(NOT_RUNNING)
        coro = app.execute(command, args or {})
        try:
            return asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            return _failed_future(NOT_RUNNING)

    def request_shutdown(self) -> None:
        if self._app is not None:
            self._app.request_shutdown()

    def shutdown(self, timeout: float = JOIN_SECONDS) -> bool:
        """Stop the service and join its thread; True when the thread ended in time."""
        thread = self._thread
        if self._closed:
            return thread is None or not thread.is_alive()
        self._closed = True
        self._timer.stop()
        if self._app is not None:
            self._app.request_shutdown()
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        alive = thread is not None and thread.is_alive()
        if alive:
            log.warning("the service thread did not stop within %s s", timeout)
        return not alive

    def _reload_context(self) -> None:
        if self._app is not None:
            self._ctx = self._app.ctx
        try:
            config = load_config(self._ctx.paths.config_file)
        except ConfigError:
            log.exception("config.toml is invalid; keeping the previous settings")
            return
        root = self._ctx.root
        if config.output.root_dir != self._ctx.config.output.root_dir:
            root = resolve_root(self._root_override, config.output.root_dir)
        self._ctx = replace(
            self._ctx,
            config=config,
            root=root,
            library_file=library_path(config.library.file, self._ctx.paths),
        )

    def _serve(self, generation: int, app: ChatImportApp) -> None:
        loop = asyncio.new_event_loop()
        if generation == self._generation:
            self._loop = loop
        try:
            loop.run_until_complete(app.run())
        except AlreadyRunning:
            self._relay.emit("already_running", (generation, None))
        except Exception as exc:
            log.exception("the ChatImport service stopped")
            self._relay.emit("failed", (generation, type(exc).__name__))
        else:
            self._relay.emit("stopped", (generation, None))
        finally:
            loop.close()

    @Slot(str, object)
    def _on_relay(self, kind: str, payload: object) -> None:
        generation, value = cast("tuple[int, Any]", payload)
        if kind == "snapshot" and generation != self._generation:
            self._polling = False
        if generation != self._generation:
            return
        if kind == "snapshot":
            self._publish(cast("dict[str, Any]", value) if isinstance(value, dict) else None)
        elif kind == "failed":
            self._failed_type = str(value)
            self.failed.emit(self._failed_type)
            self._publish(None)
        elif kind == "already_running":
            self.already_running.emit()
        elif kind == "joined":
            self._publish(None)
            if callable(value):
                value()
        else:
            self.stopped.emit()
            self._publish(None)

    def _poll(self) -> None:
        if self._polling or self._closed:
            return
        self._polling = True
        generation = self._generation
        future = self.execute("status")
        future.add_done_callback(lambda done: self._status_done(generation, done))

    def _status_done(self, generation: int, future: Future[CommandResult]) -> None:
        data: dict[str, Any] | None = None
        try:
            result = future.result()
        except Exception:
            log.debug("status poll failed", exc_info=True)
        else:
            if result.ok:
                data = result.data
        self._relay.emit("snapshot", (generation, data))

    def _publish(self, live: dict[str, Any] | None) -> None:
        self._polling = False
        data = live if live is not None else self._from_file()
        if data is not None:
            self._last = data
            self.snapshot.emit(data)

    def _from_file(self) -> dict[str, Any] | None:
        if self.is_alive and self._failed_type is None:
            service = "starting"
        elif self.needs_setup:
            service = NEEDS_SETUP
        else:
            service = "stopped"
        stored = read_snapshot(self._ctx.root)
        if stored is None:
            return (
                None if service == "starting" else {"service": service, "chats": [], "errors": []}
            )
        return {**stored, "service": service}
