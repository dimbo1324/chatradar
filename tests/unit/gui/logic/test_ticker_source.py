from __future__ import annotations

from concurrent.futures import Future
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QCoreApplication, QObject

from chatimport.gui.pages import PAGE_KEYS  # isort: skip - log_source needs pages loaded first
from chatimport.gui.models import log_source, ticker
from chatimport.gui.models.log_source import INITIAL_RECORDS, OLDER_RECORDS, LogSource
from chatimport.gui.models.log_tail import OlderBatch, PollResult
from chatimport.gui.models.ticker import SecondTicker, shared_ticker, utc_now

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from chatimport.gui.models.log_parser import LogRecord


_ = PAGE_KEYS


def test_utc_now_is_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_ticker_clock_and_animation_counting(qapp: QApplication) -> None:
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    clock = SecondTicker(lambda: fixed)
    try:
        assert clock.now() == fixed
        assert not clock.animating
        clock.release_animation()
        assert not clock.animating
        clock.acquire_animation()
        clock.acquire_animation()
        assert clock.animating
        assert clock._frame.isActive()  # pyright: ignore[reportPrivateUsage]
        clock.release_animation()
        assert clock._frame.isActive()  # pyright: ignore[reportPrivateUsage]
        clock.release_animation()
        assert not clock.animating
        assert not clock._frame.isActive()  # pyright: ignore[reportPrivateUsage]
    finally:
        clock.deleteLater()


def test_ticker_frame_signal_carries_a_sweep_fraction(qapp: QApplication) -> None:
    clock = SecondTicker()
    values: list[float] = []
    clock.frame.connect(values.append)
    clock._on_frame()  # pyright: ignore[reportPrivateUsage]
    assert len(values) == 1
    assert 0.0 <= values[0] < 1.0
    clock.deleteLater()


def test_shared_ticker_is_one_per_application(qapp: QApplication) -> None:
    first = shared_ticker()
    assert shared_ticker() is first
    assert first.parent() is QCoreApplication.instance()


def test_shared_ticker_without_an_application(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ticker.QCoreApplication, "instance", staticmethod(lambda: None))
    orphan = shared_ticker()
    try:
        assert orphan.parent() is None
    finally:
        orphan.deleteLater()


class InlineRunner:
    def __init__(self, parent: QObject | None = None) -> None:
        self.parent = parent

    def submit(self, func: Callable[[], Any], on_done: Callable[[Future[Any]], None]) -> None:
        future: Future[Any] = Future()
        try:
            future.set_result(func())
        except Exception as error:
            future.set_exception(error)
        on_done(future)


class Recorder(QObject):
    def __init__(self, source: LogSource) -> None:
        super().__init__()
        self.events: list[tuple[str, tuple[Any, ...]]] = []
        for name in ("loaded", "appended", "older", "exists_changed", "rotated", "busy_changed"):
            getattr(source, name).connect(self._make(name))
        source.failed.connect(self._make("failed"))

    def _make(self, name: str) -> Callable[..., None]:
        def record(*args: Any) -> None:
            self.events.append((name, args))

        return record

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


@pytest.fixture
def clock(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[SecondTicker]:
    fake = SecondTicker()
    monkeypatch.setattr(log_source, "shared_ticker", lambda: fake)
    monkeypatch.setattr(log_source, "MainThreadRunner", InlineRunner)
    yield fake
    fake.deleteLater()


def line(n: int) -> str:
    return f"2026-10-31T20:00:{n:02d}.000Z INFO t.x: msg{n}\n"


def make_source(tmp_path: Path, text: str | None = None) -> tuple[LogSource, Recorder]:
    if text is not None:
        (tmp_path / "chatimport.log").write_text(text, encoding="utf-8")
    source = LogSource(tmp_path)
    return source, Recorder(source)


def test_start_loads_the_tail(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path, line(1) + line(2))
    assert not source.ready
    assert not source.exists
    assert not source.busy
    source.start()
    assert source.ready
    assert source.exists
    assert source.has_older
    assert recorder.names() == ["busy_changed", "busy_changed", "exists_changed", "loaded"]
    records, has_older = recorder.events[-1][1]
    assert [r.message for r in records] == ["msg1", "msg2"]
    assert has_older is True
    assert source.tail.has_older


def test_start_failure_and_cancel(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path)

    def boom(_target: int) -> list[LogRecord]:
        raise RuntimeError

    source.tail.load_tail = boom  # type: ignore[method-assign]
    source.start()
    assert recorder.names() == ["busy_changed", "busy_changed", "failed"]
    assert not source.ready
    cancelled: Future[list[LogRecord]] = Future()
    cancelled.cancel()
    source._on_loaded(cancelled)  # pyright: ignore[reportPrivateUsage]
    assert recorder.names()[-1] == "failed"


def test_initial_and_older_sizes(clock: SecondTicker, tmp_path: Path) -> None:
    source, _ = make_source(tmp_path)
    seen: list[int] = []
    source.tail.load_tail = lambda target: seen.append(target) or []  # type: ignore[method-assign,func-returns-value]
    source.start()
    source.tail.load_older = lambda target: seen.append(target) or OlderBatch([], False)  # type: ignore[method-assign]
    source.load_older()
    assert seen == [INITIAL_RECORDS, OLDER_RECORDS]


def test_load_older_flow(clock: SecondTicker, tmp_path: Path) -> None:
    (tmp_path / "chatimport.log.1").write_text(line(0), encoding="utf-8")
    source, recorder = make_source(tmp_path, line(1))
    source.start()
    recorder.events.clear()
    source.load_older()
    assert recorder.names() == ["busy_changed", "busy_changed", "older"]
    records, exhausted = recorder.events[-1][1]
    assert [r.message for r in records] == ["msg0"]
    assert isinstance(exhausted, bool)


def test_load_older_is_ignored_when_busy_or_exhausted(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path, line(1))
    source.start()
    recorder.events.clear()
    source._busy = True  # pyright: ignore[reportPrivateUsage]
    source.load_older()
    source._busy = False  # pyright: ignore[reportPrivateUsage]
    source.forget_older()
    source.load_older()
    assert recorder.events == []


def test_load_older_failure(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path, line(1))
    source.start()

    def boom(_target: int) -> OlderBatch:
        raise RuntimeError

    source.tail.load_older = boom  # type: ignore[method-assign]
    recorder.events.clear()
    source.load_older()
    assert recorder.names() == ["busy_changed", "busy_changed", "failed"]


def test_following_polls_on_the_tick_and_stops(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path, line(1))
    source.start()
    recorder.events.clear()
    source.set_following(False)
    source.set_following(True)
    source.set_following(True)
    with (tmp_path / "chatimport.log").open("a", encoding="utf-8") as handle:
        handle.write(line(2))
    clock.second.emit()
    assert recorder.names() == ["appended"]
    assert [r.message for r in recorder.events[0][1][0]] == ["msg2"]
    source.set_following(False)
    with (tmp_path / "chatimport.log").open("a", encoding="utf-8") as handle:
        handle.write(line(3))
    clock.second.emit()
    assert recorder.names() == ["appended"]


def test_set_following_catches_up_at_once(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path, line(1))
    source.start()
    with (tmp_path / "chatimport.log").open("a", encoding="utf-8") as handle:
        handle.write(line(2))
    recorder.events.clear()
    source.set_following(True)
    assert recorder.names() == ["appended"]
    source.set_following(False)


def test_poll_does_nothing_before_the_first_load_or_while_busy(
    clock: SecondTicker, tmp_path: Path
) -> None:
    source, recorder = make_source(tmp_path, line(1))
    source._poll()  # pyright: ignore[reportPrivateUsage]
    source.start()
    source._busy = True  # pyright: ignore[reportPrivateUsage]
    (tmp_path / "chatimport.log").write_text(line(1) + line(2), encoding="utf-8")
    recorder.events.clear()
    source._poll()  # pyright: ignore[reportPrivateUsage]
    assert recorder.events == []


def test_poll_reports_existence_changes_and_rotation(clock: SecondTicker, tmp_path: Path) -> None:
    source, recorder = make_source(tmp_path, line(1))
    source.start()
    recorder.events.clear()
    (tmp_path / "chatimport.log").unlink()
    source._poll()  # pyright: ignore[reportPrivateUsage]
    assert recorder.events == [("exists_changed", (False,))]
    assert not source.exists
    (tmp_path / "chatimport.log").write_text(line(9), encoding="utf-8")
    recorder.events.clear()
    source._poll()  # pyright: ignore[reportPrivateUsage]
    assert recorder.names() == ["exists_changed", "appended"]
    source.tail.poll = lambda: PollResult(rotated=True)  # type: ignore[method-assign]
    recorder.events.clear()
    source._poll()  # pyright: ignore[reportPrivateUsage]
    assert recorder.names() == ["rotated"]


def test_poll_schedules_another_read_when_more_is_waiting(
    clock: SecondTicker, tmp_path: Path, qapp: QApplication
) -> None:
    source, _ = make_source(tmp_path, line(1))
    source.start()
    results = iter([PollResult(more=True), PollResult()])
    calls: list[int] = []

    def fake_poll() -> PollResult:
        calls.append(1)
        return next(results)

    source.tail.poll = fake_poll  # type: ignore[method-assign]
    source._poll()  # pyright: ignore[reportPrivateUsage]
    qapp.processEvents()
    assert len(calls) == 2
