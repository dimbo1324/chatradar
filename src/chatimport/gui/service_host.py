"""`ServiceHost`: the archive service on a background asyncio thread, seen from the Qt thread.

The window never touches the service directly. `execute` schedules a command on the service's
loop and returns a `concurrent.futures.Future`; every two seconds the host asks for `status`
and publishes the result as the `snapshot` signal. Whatever happens on the service thread
reaches Qt through an internal signal, so every public signal fires on the main thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, Final, cast

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from chatimport.control import AlreadyRunning
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
    ) -> None:
        super().__init__()
        self._app = app_factory(ctx, notifier)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._serve, name="chatimport-service")
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
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()
        self._timer.start()
        self._poll()

    def execute(self, command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        loop = self._loop
        if loop is None or loop.is_closed() or not self._thread.is_alive():
            return _failed_future(NOT_RUNNING)
        coro = self._app.execute(command, args or {})
        try:
            return asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()
            return _failed_future(NOT_RUNNING)

    def request_shutdown(self) -> None:
        self._app.request_shutdown()

    def shutdown(self, timeout: float = JOIN_SECONDS) -> bool:
        """Stop the service and join its thread; True when the thread ended in time."""
        if self._closed:
            return not self._thread.is_alive()
        self._closed = True
        self._timer.stop()
        self._app.request_shutdown()
        if self._thread.is_alive():
            self._thread.join(timeout)
        alive = self._thread.is_alive()
        if alive:
            log.warning("the service thread did not stop within %s s", timeout)
        return not alive

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._app.run())
        except AlreadyRunning:
            self._relay.emit("already_running", None)
        except Exception as exc:
            log.exception("the ChatImport service stopped")
            self._relay.emit("failed", type(exc).__name__)
        else:
            self._relay.emit("stopped", None)
        finally:
            loop.close()

    @Slot(str, object)
    def _on_relay(self, kind: str, payload: object) -> None:
        if kind == "snapshot":
            self._publish(cast("dict[str, Any]", payload) if isinstance(payload, dict) else None)
        elif kind == "failed":
            self._failed_type = str(payload)
            self.failed.emit(self._failed_type)
            self._publish(None)
        elif kind == "already_running":
            self.already_running.emit()
        else:
            self.stopped.emit()
            self._publish(None)

    def _poll(self) -> None:
        if self._polling or self._closed:
            return
        self._polling = True
        future = self.execute("status")
        future.add_done_callback(self._status_done)

    def _status_done(self, future: Future[CommandResult]) -> None:
        data: dict[str, Any] | None = None
        try:
            result = future.result()
        except Exception:
            log.debug("status poll failed", exc_info=True)
        else:
            if result.ok:
                data = result.data
        self._relay.emit("snapshot", data)

    def _publish(self, live: dict[str, Any] | None) -> None:
        self._polling = False
        data = live if live is not None else self._from_file()
        if data is not None:
            self._last = data
            self.snapshot.emit(data)

    def _from_file(self) -> dict[str, Any] | None:
        stored = read_snapshot(self._app.ctx.root)
        if stored is None:
            return None
        if self._failed_type is not None or not self._thread.is_alive():
            service = "stopped"
        else:
            service = "starting"
        return {**stored, "service": service}
