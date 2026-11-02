"""Search page tests: widgets are dropped after each test, and the worker thread is scripted."""

from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from chatimport.gui.pages import search as search_module
from chatimport.gui.pages.search import SearchPage
from tests.unit.gui.search.fakes import NOW, FakeBackend

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from chatimport.gui.context import GuiContext
    from chatimport.search_types import SearchBackend


class ScriptedWorker:
    """Stands in for `SearchWorker`: jobs run at once, or wait until the test resolves them."""

    last: ScriptedWorker | None = None
    manual = False

    def __init__(self, root: Callable[[], Path], factory: Callable[[Path], SearchBackend | None]):
        self._root = root
        self._factory = factory
        self.pending: list[tuple[Callable[[SearchBackend | None], Any], Future[Any]]] = []
        self.closed = False
        ScriptedWorker.last = self

    def run(self, job: Callable[[SearchBackend | None], Any]) -> Future[Any]:
        future: Future[Any] = Future()
        if self.manual:
            self.pending.append((job, future))
        else:
            self._execute(job, future)
        return future

    def _execute(self, job: Callable[[SearchBackend | None], Any], future: Future[Any]) -> None:
        try:
            future.set_result(job(self._factory(self._root())))
        except Exception as error:
            future.set_exception(error)

    def resolve(self, index: int) -> None:
        job, future = self.pending[index]
        self._execute(job, future)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def drop_top_level_widgets(qapp: QApplication) -> Iterator[None]:
    yield
    for widget in QApplication.topLevelWidgets():
        if shiboken6.isValid(widget):
            widget.hide()
            shiboken6.delete(widget)
    qapp.processEvents()


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def make_page(
    gui: GuiContext, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., SearchPage]:
    monkeypatch.setattr(search_module, "SearchWorker", ScriptedWorker)

    def build(*, manual: bool = False, present: bool = True) -> SearchPage:
        ScriptedWorker.manual = manual
        page = SearchPage(
            gui, backend_factory=lambda _root: backend if present else None, clock=lambda: NOW
        )
        return page

    return build


def worker_of(page: SearchPage) -> ScriptedWorker:
    worker = page._worker  # pyright: ignore[reportPrivateUsage]
    assert isinstance(worker, ScriptedWorker)
    return worker
