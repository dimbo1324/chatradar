"""Settings page fakes: a synchronous-on-demand runner, a fake Task Scheduler and a fake host."""

from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import autostart
from chatimport.gui.context import GuiContext
from chatimport.gui.pages import settings_system, settings_telegram
from tests.unit.gui.conftest import FakeBridge

if TYPE_CHECKING:
    from collections.abc import Callable

    from chatimport.context import ServiceContext
    from chatimport.gui.kit import UiKit
    from chatimport.gui.settings import GuiSettingsStore


class DeferredRunner:
    """Runs submitted work inline but delivers the finished future only on `flush`."""

    def __init__(self, parent: object = None) -> None:
        self.pending: list[tuple[Future[Any], Callable[[Future[Any]], None]]] = []

    def submit(
        self, func: Callable[[], Any], on_done: Callable[[Future[Any]], None]
    ) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(func())
        except Exception as error:
            future.set_exception(error)
        self.pending.append((future, on_done))
        return future

    def flush(self) -> None:
        pending, self.pending = self.pending, []
        for future, on_done in pending:
            on_done(future)


class FakeControl(FakeBridge):
    """A bridge that also implements `ServiceControl`."""

    def __init__(self, context: ServiceContext, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__(snapshot)
        self._context = context
        self.alive = False
        self.restarts = 0

    @property
    def context(self) -> ServiceContext:
        return self._context

    @property
    def is_alive(self) -> bool:
        return self.alive

    def start_service(self) -> bool:
        self.alive = True
        return True

    def stop_service(self, on_stopped: Callable[[], None] | None = None) -> None:
        self.alive = False
        if on_stopped is not None:
            on_stopped()

    def restart(self) -> None:
        self.restarts += 1


class FakeAutostart:
    def __init__(self) -> None:
        self.supported = True
        self.status_result: autostart.AutostartStatus | Exception = autostart.AutostartStatus(
            autostart.AutostartState.ABSENT
        )
        self.calls: list[str] = []

    def status(self, task: str = "", *, executable: str | None = None) -> Any:
        self.calls.append("status")
        return self._result()

    def enable(self, task: str = "", *, executable: str | None = None) -> Any:
        self.calls.append("enable")
        self._result()
        self.status_result = autostart.AutostartStatus(autostart.AutostartState.ENABLED)
        return self.status_result

    def disable(self, task: str = "") -> Any:
        self.calls.append("disable")
        self._result()
        self.status_result = autostart.AutostartStatus(autostart.AutostartState.ABSENT)
        return self.status_result

    def _result(self) -> Any:
        if isinstance(self.status_result, Exception):
            raise self.status_result
        return self.status_result


@pytest.fixture(autouse=True)
def fake_autostart(monkeypatch: pytest.MonkeyPatch) -> FakeAutostart:
    fake = FakeAutostart()
    monkeypatch.setattr(autostart, "supported", lambda: fake.supported)
    monkeypatch.setattr(autostart, "status", fake.status)
    monkeypatch.setattr(autostart, "enable", fake.enable)
    monkeypatch.setattr(autostart, "disable", fake.disable)
    monkeypatch.setattr(settings_system, "MainThreadRunner", DeferredRunner)
    monkeypatch.setattr(settings_telegram, "MainThreadRunner", DeferredRunner)
    return fake


@pytest.fixture
def control(service_context: ServiceContext) -> FakeControl:
    return FakeControl(service_context)


@pytest.fixture
def control_gui(
    kit: UiKit, store: GuiSettingsStore, control: FakeControl, service_context: ServiceContext
) -> GuiContext:
    return GuiContext(
        service=service_context,
        theme=kit.theme,
        language=kit.language,
        zoom=kit.zoom,
        settings=store,
        bridge=control,  # type: ignore[arg-type]  # a structural stand-in
    )
