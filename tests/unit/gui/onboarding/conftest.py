"""Wizard fakes: a synchronous runner, a fake Task Scheduler, a fake sign-in dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
import shiboken6
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from chatimport import autostart
from chatimport.gui import setup_steps, setup_steps_run
from chatimport.gui.context import GuiContext
from tests.unit.gui.pages_c.conftest import DeferredRunner, FakeAutostart, FakeControl

if TYPE_CHECKING:
    from collections.abc import Iterator

    from chatimport.context import ServiceContext
    from chatimport.gui.kit import UiKit
    from chatimport.gui.settings import GuiSettingsStore

__all__ = ["DeferredRunner", "FakeAutostart", "FakeControl", "FakeLoginDialog"]


class FakeLoginDialog(QObject):
    signed_in = Signal(str)
    created: ClassVar[list[FakeLoginDialog]] = []
    handle: ClassVar[str] = "@newcomer"

    def __init__(self, gui: Any, hooks: Any, control: Any, parent: Any) -> None:
        super().__init__()
        self.args = (gui, hooks, control, parent)
        FakeLoginDialog.created.append(self)

    def exec(self) -> int:
        self.signed_in.emit(FakeLoginDialog.handle)
        return 1


@pytest.fixture(autouse=True)
def drop_top_level_widgets(qapp: QApplication) -> Iterator[None]:
    yield
    for widget in QApplication.topLevelWidgets():
        if shiboken6.isValid(widget):
            widget.hide()
            shiboken6.delete(widget)
    qapp.processEvents()


@pytest.fixture(autouse=True)
def fake_autostart(monkeypatch: pytest.MonkeyPatch) -> FakeAutostart:
    fake = FakeAutostart()
    monkeypatch.setattr(autostart, "supported", lambda: fake.supported)
    monkeypatch.setattr(autostart, "status", fake.status)
    monkeypatch.setattr(autostart, "enable", fake.enable)
    monkeypatch.setattr(autostart, "disable", fake.disable)
    monkeypatch.setattr(setup_steps_run, "MainThreadRunner", DeferredRunner)
    FakeLoginDialog.created.clear()
    monkeypatch.setattr(setup_steps, "LoginDialog", FakeLoginDialog)
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
