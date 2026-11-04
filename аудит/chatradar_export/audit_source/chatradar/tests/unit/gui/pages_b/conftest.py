"""Fixtures of the Log and Data page tests: toast recorder, runner cleanup, event pumping."""

from __future__ import annotations

import gc
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QEvent

from chatimport.gui.pages import data_common, log, support
from chatimport.gui.pages.data import DataPage
from tests.unit.gui.pages_b.archive import build_archive

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtWidgets import QApplication

    from chatimport.gui.context import GuiContext

TIMEOUT_SECONDS = 5.0


class Toasts:
    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def __call__(self, widget: QObject, tone: str, message: str) -> None:
        self.items.append((tone, message))

    def tones(self) -> list[str]:
        return [tone for tone, _message in self.items]

    def last(self) -> tuple[str, str]:
        return self.items[-1]


@pytest.fixture(autouse=True)
def runners(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[support.MainThreadRunner]]:
    created: list[support.MainThreadRunner] = []
    original = support.MainThreadRunner.__init__

    def tracked(self: support.MainThreadRunner, parent: QObject | None = None) -> None:
        original(self, parent)
        created.append(self)

    monkeypatch.setattr(support.MainThreadRunner, "__init__", tracked)
    yield created
    for runner in created:
        runner._pool.shutdown(wait=True)  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def toasts(monkeypatch: pytest.MonkeyPatch) -> Toasts:
    recorder = Toasts()
    monkeypatch.setattr(log, "notify", recorder)
    monkeypatch.setattr(data_common, "notify", recorder)
    return recorder


@pytest.fixture
def settle(qapp: QApplication) -> Callable[[Callable[[], bool]], None]:
    def wait(condition: Callable[[], bool]) -> None:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while not condition():
            qapp.processEvents()
            if time.monotonic() > deadline:
                raise AssertionError("condition not reached")
            time.sleep(0.002)
        qapp.processEvents()

    return wait


class Answers:
    def __init__(self) -> None:
        self.accept = True
        self.asked: list[str] = []


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> Answers:
    from PySide6.QtWidgets import QMessageBox

    result = Answers()

    def fake_exec(self: QMessageBox) -> int:
        result.asked.append(self.text())
        return 0

    def fake_clicked(self: QMessageBox) -> object:
        buttons = self.buttons()
        return buttons[0] if result.accept else buttons[1]

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)
    return result


class Opened:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.ok = True


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> Opened:
    from PySide6.QtGui import QDesktopServices

    result = Opened()

    def fake_open(url: QUrl) -> bool:
        result.urls.append(str(Path(url.toLocalFile())))
        return result.ok

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(fake_open))
    return result


class Clipboard:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


@pytest.fixture
def clipboard(monkeypatch: pytest.MonkeyPatch) -> Clipboard:
    from PySide6.QtGui import QGuiApplication

    result = Clipboard()
    monkeypatch.setattr(QGuiApplication, "clipboard", staticmethod(lambda: result))
    return result


@pytest.fixture
def data_page(gui: GuiContext, qapp: QApplication) -> DataPage:
    build_archive(gui.current.root)
    return DataPage(gui)


@pytest.fixture(autouse=True)
def drop_widgets(qapp: QApplication) -> Iterator[None]:
    """Every live widget is restyled when a later test applies the application stylesheet."""
    yield
    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
