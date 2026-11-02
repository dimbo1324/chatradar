# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.gui.pages import search_worker
from chatimport.gui.pages.search_worker import THREAD_NAME, SearchWorker, default_backend_factory
from tests.unit.gui.search.fakes import FakeBackend

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def workers() -> Iterator[list[SearchWorker]]:
    created: list[SearchWorker] = []
    yield created
    for worker in created:
        worker.close()
        worker._pool.shutdown(wait=True)  # pyright: ignore[reportPrivateUsage]


def make(workers: list[SearchWorker], root: Path, factory: Any) -> SearchWorker:
    worker = SearchWorker(lambda: root, factory)
    workers.append(worker)
    return worker


def test_default_factory_without_the_module(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> Any:
        raise ImportError("no module")

    monkeypatch.setattr(search_worker, "importlib", SimpleNamespace(import_module=missing))
    assert default_backend_factory(Path("data")) is None


def test_default_factory_without_an_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(import_module=lambda _name: SimpleNamespace(open_reader=None))
    monkeypatch.setattr(search_worker, "importlib", fake)
    assert default_backend_factory(Path("data")) is None


def test_default_factory_opens_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeBackend()
    roots: list[Path] = []

    def open_reader(root: Path) -> FakeBackend:
        roots.append(root)
        return backend

    module = SimpleNamespace(open_reader=open_reader)
    fake = SimpleNamespace(import_module=lambda _name: module)
    monkeypatch.setattr(search_worker, "importlib", fake)
    assert default_backend_factory(Path("data")) is backend
    assert roots == [Path("data")]


def test_jobs_run_on_one_dedicated_thread(workers: list[SearchWorker], tmp_path: Path) -> None:
    backend = FakeBackend()
    opened: list[int] = []

    def factory(_root: Path) -> FakeBackend:
        opened.append(threading.get_ident())
        return backend

    worker = make(workers, tmp_path, factory)
    first = worker.run(lambda b: threading.get_ident() if b is not None else 0).result(timeout=5)
    second = worker.run(lambda b: threading.get_ident() if b is not None else 0).result(timeout=5)
    assert first == second != threading.get_ident()
    assert opened == [first]


def test_the_thread_has_a_name(workers: list[SearchWorker], tmp_path: Path) -> None:
    worker = make(workers, tmp_path, lambda _root: None)
    name = worker.run(lambda _b: threading.current_thread().name).result(timeout=5)
    assert name.startswith(THREAD_NAME)


def test_the_backend_is_opened_once_and_passed_to_jobs(
    workers: list[SearchWorker], tmp_path: Path
) -> None:
    backend = FakeBackend()
    calls: list[Path] = []

    def factory(root: Path) -> FakeBackend:
        calls.append(root)
        return backend

    worker = make(workers, tmp_path, factory)
    assert worker.run(lambda b: b).result(timeout=5) is backend
    assert worker.run(lambda b: b).result(timeout=5) is backend
    assert calls == [tmp_path]


def test_a_missing_index_is_retried(workers: list[SearchWorker], tmp_path: Path) -> None:
    backend = FakeBackend()
    answers: list[FakeBackend | None] = [None, backend]
    worker = make(workers, tmp_path, lambda _root: answers.pop(0))
    assert worker.run(lambda b: b).result(timeout=5) is None
    assert worker.run(lambda b: b).result(timeout=5) is backend


def test_a_new_root_reopens_the_backend(workers: list[SearchWorker], tmp_path: Path) -> None:
    roots = [tmp_path / "one", tmp_path / "two"]
    current = [roots[0]]
    backends: dict[Path, FakeBackend] = {root: FakeBackend() for root in roots}
    worker = SearchWorker(lambda: current[0], lambda root: backends[root])
    workers.append(worker)
    assert worker.run(lambda b: b).result(timeout=5) is backends[roots[0]]
    current[0] = roots[1]
    assert worker.run(lambda b: b).result(timeout=5) is backends[roots[1]]
    assert backends[roots[0]].closed
    assert not backends[roots[1]].closed


def test_job_errors_travel_in_the_future(workers: list[SearchWorker], tmp_path: Path) -> None:
    worker = make(workers, tmp_path, lambda _root: None)

    def boom(_backend: object) -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        worker.run(boom).result(timeout=5)


def test_close_drops_the_backend_on_the_worker_thread(
    workers: list[SearchWorker], tmp_path: Path
) -> None:
    backend = FakeBackend()
    worker = make(workers, tmp_path, lambda _root: backend)
    worker.run(lambda b: b).result(timeout=5)
    worker.close()
    worker._pool.shutdown(wait=True)  # pyright: ignore[reportPrivateUsage]
    assert backend.closed
    late = worker.run(lambda b: b)
    assert late.cancelled()
    worker.close()


def test_close_before_any_use_is_harmless(workers: list[SearchWorker], tmp_path: Path) -> None:
    worker = make(workers, tmp_path, lambda _root: None)
    worker.close()
    worker._pool.shutdown(wait=True)  # pyright: ignore[reportPrivateUsage]
    assert worker.run(lambda b: b).cancelled()


def test_a_failing_close_is_logged_without_details(
    workers: list[SearchWorker], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken(FakeBackend):
        def close(self) -> None:
            raise OSError("secret detail")

    worker = make(workers, tmp_path, lambda _root: Broken())
    worker.run(lambda b: b).result(timeout=5)
    with caplog.at_level(logging.WARNING, logger=search_worker.__name__):
        worker.close()
        worker._pool.shutdown(wait=True)  # pyright: ignore[reportPrivateUsage]
    assert "OSError" in caplog.text
    assert "secret detail" not in caplog.text
