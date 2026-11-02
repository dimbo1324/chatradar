# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from chatimport import app as app_module
from chatimport.commands import CommandResult
from chatimport.control import AlreadyRunning
from chatimport.gui.service_host import (
    NEEDS_SETUP,
    NOT_RUNNING,
    ServiceHost,
    default_app_factory,
)
from chatimport.ports import ChatImportError
from chatimport.status import STATUS_FILE

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from chatimport.context import ServiceContext
    from chatimport.runtime import Notifier

CREDENTIALS = '[telegram]\napi_id = 12345\napi_hash = "abcdef"\n'


class FakeApp:
    """A stand-in for `ChatImportApp` whose `run` lives on the host's loop thread."""

    instances: ClassVar[list[FakeApp]] = []
    mode = "serve"

    def __init__(self, ctx: ServiceContext, notifier: Notifier) -> None:
        self.ctx = ctx
        self.notifier = notifier
        self.mode = type(self).mode
        self.ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self.shutdown_requests = 0
        type(self).instances.append(self)

    async def run(self) -> None:
        if self.mode == "already":
            raise AlreadyRunning("busy")
        if self.mode == "fail":
            raise RuntimeError("boom")
        if self.mode == "exit":
            return
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self.ready.set()
        await self._stop.wait()

    def request_shutdown(self) -> None:
        self.shutdown_requests += 1
        if self.mode == "stuck":
            return
        self.release()

    def release(self) -> None:
        loop, stop = self._loop, self._stop
        if loop is None or stop is None:
            return
        try:
            loop.call_soon_threadsafe(stop.set)
        except RuntimeError:
            return

    async def execute(self, command: str, args: dict[str, Any]) -> CommandResult:
        return CommandResult(True, data={"service": "running", "chats": [], "errors": []})


@pytest.fixture(autouse=True)
def fake_app_state() -> Iterator[None]:
    FakeApp.instances = []
    FakeApp.mode = "serve"
    yield
    for app in FakeApp.instances:
        app.release()
    for thread in threading.enumerate():
        if thread.name.startswith("chatimport-service"):
            thread.join(5)


@pytest.fixture
def make_host(
    qapp: QApplication, service_context: ServiceContext
) -> Iterator[Callable[..., ServiceHost]]:
    hosts: list[ServiceHost] = []

    def build(**kwargs: Any) -> ServiceHost:
        host = ServiceHost(service_context, _Quiet(), app_factory=FakeApp, **kwargs)  # type: ignore[arg-type]
        hosts.append(host)
        return host

    yield build
    for host in hosts:
        host.shutdown(5)


class _Quiet:
    def notify(self, level: object, title: str, message: str) -> None:
        return None


def pump(qapp: QApplication, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        qapp.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.002)


def configure(ctx: ServiceContext, *, session: bool = True, extra: str = "") -> None:
    ctx.paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    ctx.paths.config_file.write_text(CREDENTIALS + extra, encoding="utf-8")
    if session:
        ctx.paths.session_file.parent.mkdir(parents=True, exist_ok=True)
        ctx.paths.session_file.write_bytes(b"x")


def test_needs_setup_variants(make_host: Callable[..., ServiceHost], tmp_path: Path) -> None:
    host = make_host()
    assert host.needs_setup
    configure(host.context, session=False)
    host._reload_context()
    assert host.needs_setup
    configure(host.context)
    assert not host.needs_setup
    assert host.context is host._ctx
    assert not host.is_alive
    assert host.last_snapshot is None
    assert host.failed_type is None


def test_default_app_factory(
    service_context: ServiceContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Stub:
        def __init__(self, ctx: ServiceContext, *, notifier: object) -> None:
            self.args = (ctx, notifier)

    monkeypatch.setattr(app_module, "ChatImportApp", Stub)
    made = default_app_factory(service_context, _Quiet())  # type: ignore[arg-type]
    assert isinstance(made, Stub)


def test_start_without_setup_publishes_needs_setup(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    seen: list[dict[str, Any]] = []
    host.snapshot.connect(seen.append)
    host.start()
    assert seen[0]["service"] == NEEDS_SETUP
    assert host.last_snapshot == seen[0]
    pump(qapp, lambda: len(seen) >= 2)
    assert not host.start_service()
    result = host.execute("status").exception()
    assert isinstance(result, ChatImportError)
    assert str(result) == NOT_RUNNING


def test_running_service_lifecycle(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    configure(host.context)
    seen: list[dict[str, Any]] = []
    host.snapshot.connect(seen.append)
    stopped_calls: list[int] = []
    assert host.start_service()
    assert not host.start_service()
    app = FakeApp.instances[0]
    assert app.ready.wait(5)
    assert host.is_alive
    reply = host.execute("status", None).result(timeout=5)
    assert reply.ok
    host._poll()
    host._poll()
    pump(qapp, lambda: any(s.get("service") == "running" for s in seen))
    host.request_shutdown()
    assert app.shutdown_requests == 1
    host.stop_service(lambda: stopped_calls.append(1))
    pump(qapp, lambda: stopped_calls == [1])
    assert not host.is_alive
    host.stop_service()
    host.stop_service(lambda: stopped_calls.append(2))
    assert stopped_calls == [1, 2]
    snapshot_after = seen[-1]
    assert snapshot_after["service"] in {"stopped", "starting"}


def test_restart_starts_a_new_generation(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    configure(host.context)
    assert host.start_service()
    assert FakeApp.instances[0].ready.wait(5)
    first_generation = host._generation
    host.restart()
    pump(qapp, lambda: len(FakeApp.instances) == 2)
    assert host._generation == first_generation + 1
    assert FakeApp.instances[1].ready.wait(5)
    assert host.is_alive


def test_stop_service_without_callback_when_running(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    configure(host.context)
    host.start_service()
    assert FakeApp.instances[0].ready.wait(5)
    host.stop_service()
    pump(qapp, lambda: not host.is_alive)
    qapp.processEvents()
    pump(qapp, lambda: True)


def test_failed_service_reports_type(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    FakeApp.mode = "fail"
    host = make_host()
    configure(host.context)
    kinds: list[str] = []
    seen: list[dict[str, Any]] = []
    host.failed.connect(kinds.append)
    host.snapshot.connect(seen.append)
    host.start_service()
    pump(qapp, lambda: kinds == ["RuntimeError"])
    assert host.failed_type == "RuntimeError"
    assert seen
    assert not host.start_service() or host.failed_type is None


def test_already_running_signal(qapp: QApplication, make_host: Callable[..., ServiceHost]) -> None:
    FakeApp.mode = "already"
    host = make_host()
    configure(host.context)
    flags: list[bool] = []
    host.already_running.connect(lambda: flags.append(True))
    host.start_service()
    pump(qapp, lambda: flags == [True])


def test_clean_exit_emits_stopped(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    FakeApp.mode = "exit"
    host = make_host()
    configure(host.context)
    flags: list[bool] = []
    host.stopped.connect(lambda: flags.append(True))
    host.start_service()
    pump(qapp, lambda: flags == [True])


def test_stale_generation_events_are_dropped(
    make_host: Callable[..., ServiceHost],
) -> None:
    host = make_host()
    seen: list[dict[str, Any]] = []
    host.snapshot.connect(seen.append)
    host._polling = True
    host._on_relay("snapshot", (99, {"service": "running"}))
    assert not host._polling
    host._on_relay("failed", (99, "X"))
    assert seen == []
    assert host.failed_type is None


def test_relay_kinds_on_current_generation(make_host: Callable[..., ServiceHost]) -> None:
    host = make_host()
    seen: list[dict[str, Any]] = []
    host.snapshot.connect(seen.append)
    host._on_relay("snapshot", (0, {"service": "running", "chats": []}))
    assert seen[-1]["service"] == "running"
    host._on_relay("snapshot", (0, "not a dict"))
    assert seen[-1]["service"] == NEEDS_SETUP
    ran: list[int] = []
    host._on_relay("joined", (0, lambda: ran.append(1)))
    host._on_relay("joined", (0, None))
    assert ran == [1]


def test_poll_guards_and_status_failure(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    host._polling = True
    host._poll()
    host._polling = False
    host._closed = True
    host._poll()
    assert not host._polling
    host._closed = False
    from concurrent.futures import Future

    broken: Future[CommandResult] = Future()
    broken.set_exception(RuntimeError("x"))
    bad: Future[CommandResult] = Future()
    bad.set_result(CommandResult(False, "no"))
    host._status_done(0, broken)
    host._status_done(0, bad)
    qapp.processEvents()


def test_execute_when_loop_cannot_schedule(
    qapp: QApplication, make_host: Callable[..., ServiceHost], monkeypatch: pytest.MonkeyPatch
) -> None:
    host = make_host()
    configure(host.context)
    host.start_service()
    assert FakeApp.instances[0].ready.wait(5)

    def refuse(coro: Any, loop: Any) -> None:
        raise RuntimeError("loop closed")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", refuse)
    failure = host.execute("status").exception()
    assert isinstance(failure, ChatImportError)
    monkeypatch.undo()


def test_from_file_uses_stored_snapshot(make_host: Callable[..., ServiceHost]) -> None:
    host = make_host()
    configure(host.context)
    host._reload_context()
    host.context.root.mkdir(parents=True, exist_ok=True)
    (host.context.root / STATUS_FILE).write_text(
        json.dumps({"chats": [{"chat_id": 1}], "service": "running"}), encoding="utf-8"
    )
    stored = host._from_file()
    assert stored is not None
    assert stored["service"] == "stopped"
    host.start_service()
    assert FakeApp.instances[0].ready.wait(5)
    alive = host._from_file()
    assert alive is not None
    assert alive["service"] == "starting"
    host._failed_type = "Boom"
    failed = host._from_file()
    assert failed is not None
    assert failed["service"] == "stopped"
    host._failed_type = None
    (host.context.root / STATUS_FILE).unlink()
    assert host._from_file() is None


def test_from_file_without_snapshot(make_host: Callable[..., ServiceHost]) -> None:
    host = make_host()
    configure(host.context)
    host._reload_context()
    stopped = host._from_file()
    assert stopped == {"service": "stopped", "chats": [], "errors": []}


def test_reload_context_keeps_settings_on_bad_config(
    make_host: Callable[..., ServiceHost],
) -> None:
    host = make_host()
    configure(host.context)
    host._reload_context()
    good = host._ctx.config
    host.context.paths.config_file.write_text("[telegram\nbroken", encoding="utf-8")
    host._reload_context()
    assert host._ctx.config == good


def test_reload_context_follows_new_root(
    make_host: Callable[..., ServiceHost], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CHATIMPORT_ROOT")
    host = make_host()
    other = (tmp_path / "elsewhere").as_posix()
    configure(host.context, extra=f'[output]\nroot_dir = "{other}"\n')
    host._reload_context()
    assert "elsewhere" in host._ctx.root.parts
    host._reload_context()
    configure(host.context, extra=f'[output]\nroot_dir = "{other}"\n')
    host._app = FakeApp(replace(host._ctx), _Quiet())  # type: ignore[arg-type]
    host._reload_context()
    assert host._ctx.config.output.root_dir == other


def test_shutdown_paths(qapp: QApplication, make_host: Callable[..., ServiceHost]) -> None:
    idle = make_host()
    assert idle.shutdown()
    assert idle.shutdown()
    FakeApp.mode = "stuck"
    stuck = make_host()
    configure(stuck.context)
    stuck.start_service()
    app = FakeApp.instances[0]
    assert app.ready.wait(5)
    assert stuck.shutdown(0.01) is False
    assert stuck.shutdown() is False
    app.release()
    pump(qapp, lambda: not stuck.is_alive)
    assert stuck.shutdown()

    FakeApp.mode = "serve"
    clean = make_host()
    clean.start_service()
    assert FakeApp.instances[1].ready.wait(5)
    assert clean.shutdown(5)


def test_start_with_setup_runs_service(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    configure(host.context)
    host.start()
    assert FakeApp.instances[0].ready.wait(5)
    assert host.is_alive
    assert host.shutdown(5)


def test_request_shutdown_without_app_and_stale_serve(
    qapp: QApplication, make_host: Callable[..., ServiceHost]
) -> None:
    host = make_host()
    host.request_shutdown()
    FakeApp.mode = "exit"
    app = FakeApp(host.context, _Quiet())  # type: ignore[arg-type]
    host._generation = 5
    host._serve(1, app)  # type: ignore[arg-type]
    assert host._loop is None
    qapp.processEvents()
