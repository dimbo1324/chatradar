"""Qt tests run offscreen on one shared application; settings and files live in `tmp_path`."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from chatimport.commands import CommandResult
from chatimport.context import ServiceContext, load_context
from chatimport.gui.context import GuiContext
from chatimport.gui.kit import UiKit, build_kit
from chatimport.gui.settings import GuiSettingsStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class FakeBridge(QObject):
    """The service bridge without a service: records commands, answers from `replies`."""

    snapshot = Signal(dict)

    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.last_snapshot = snapshot
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.replies: dict[str, CommandResult] = {}

    def execute(self, command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        self.calls.append((command, args or {}))
        future: Future[CommandResult] = Future()
        future.set_result(self.replies.get(command, CommandResult(True)))
        return future


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else QApplication([])


@pytest.fixture
def service_context(tmp_path: Path) -> ServiceContext:
    return load_context(str(tmp_path / "data"), base=tmp_path / "app")


@pytest.fixture
def store(tmp_path: Path) -> GuiSettingsStore:
    return GuiSettingsStore(tmp_path / "gui.json")


@pytest.fixture
def kit(qapp: QApplication, store: GuiSettingsStore) -> Iterator[UiKit]:
    built = build_kit(store, qapp)
    yield built
    built.language.set_language("en")


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def gui(
    kit: UiKit, store: GuiSettingsStore, bridge: FakeBridge, service_context: ServiceContext
) -> GuiContext:
    return GuiContext(
        service=service_context,
        theme=kit.theme,
        language=kit.language,
        zoom=kit.zoom,
        settings=store,
        bridge=bridge,  # type: ignore[arg-type]  # a structural stand-in
    )
