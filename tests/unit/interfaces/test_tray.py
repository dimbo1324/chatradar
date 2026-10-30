"""Tray tests: pystray, tkinter, the service and the OS openers are all replaced by fakes."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import types
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import app as app_module
from chatimport import tray
from chatimport.control import AlreadyRunning, CommandResult
from chatimport.paths import normalize_root
from chatimport.runtime import Level
from tests.fakes import RecordingNotifier

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from tests.unit.interfaces.conftest import Env


def wait_until(predicate: Callable[[], object], timeout: float = 5.0) -> bool:
    ticker = threading.Event()
    waited = 0.0
    while not predicate():
        if waited >= timeout:
            return False
        ticker.wait(0.005)
        waited += 0.005
    return True


class FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items: Any) -> None:
        self.items = items


class FakeMenuItem:
    def __init__(self, text: Any, action: Any, *, enabled: bool = True) -> None:
        self.text = text
        self.action = action
        self.enabled = enabled

    def label(self) -> str:
        text: Any = self.text
        return str(text(self)) if callable(text) else str(text)


class FakeIcon:
    last: FakeIcon
    script: Callable[[FakeIcon], None] | None = None

    def __init__(self, name: str, image: Any, title: str, menu: FakeMenu) -> None:
        self.name = name
        self.icon = image
        self.title = title
        self.menu = menu
        self.visible = False
        self.toasts: list[tuple[str, str | None]] = []
        self.menu_updates = 0
        self.notify_error: Exception | None = None
        self.update_error: Exception | None = None
        self.stopped = threading.Event()
        FakeIcon.last = self

    def run(self, setup: Callable[[FakeIcon], None] | None = None) -> None:
        if setup is not None:
            setup(self)
        if FakeIcon.script is not None:
            FakeIcon.script(self)
        self.stopped.wait(10)

    def stop(self) -> None:
        self.stopped.set()

    def notify(self, message: str, title: str | None = None) -> None:
        if self.notify_error is not None:
            raise self.notify_error
        self.toasts.append((message, title))

    def update_menu(self) -> None:
        if self.update_error is not None:
            raise self.update_error
        self.menu_updates += 1

    def click(self, label: str) -> None:
        find_item(self.menu, label).action()


def find_item(menu: FakeMenu, label: str) -> FakeMenuItem:
    for item in menu.items:
        if isinstance(item, FakeMenuItem):
            if item.label() == label:
                return item
            if isinstance(item.action, FakeMenu):
                try:
                    return find_item(item.action, label)
                except LookupError:
                    continue
    raise LookupError(label)


class FakeApp:
    last: FakeApp

    def __init__(self, ctx: Any, *, notifier: Any) -> None:
        self.ctx = ctx
        self.notifier = notifier
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.results: dict[str, CommandResult] = {}
        self.execute_error: Exception | None = None
        self.run_error: BaseException | None = None
        self.returns_immediately = False
        self.ignore_shutdown = False
        self.shutdown_calls = 0
        self.running = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._early = False
        FakeApp.last = self

    async def run(self) -> None:
        if self.run_error is not None:
            raise self.run_error
        if self.returns_immediately:
            return
        self._stop = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        if self._early:
            return
        self.running.set()
        await self._stop.wait()

    def request_shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.ignore_shutdown:
            return
        self.force_stop()

    def force_stop(self) -> None:
        if self._loop is None or self._stop is None:
            self._early = True
            return
        self._loop.call_soon_threadsafe(self._stop.set)

    async def execute(self, command: str, args: dict[str, Any]) -> CommandResult:
        self.executed.append((command, args))
        if self.execute_error is not None:
            raise self.execute_error
        return self.results.get(command, CommandResult(True, ""))


class LoopThread:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="test-loop")
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


@pytest.fixture
def fake_pystray(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeIcon.script = None
    monkeypatch.setattr(
        tray, "pystray", types.SimpleNamespace(Icon=FakeIcon, Menu=FakeMenu, MenuItem=FakeMenuItem)
    )
    monkeypatch.setattr(app_module, "ChatImportApp", FakeApp)


@pytest.fixture
def loop_thread() -> Iterator[LoopThread]:
    thread = LoopThread()
    yield thread
    thread.stop()


@pytest.fixture
def parts(env: Env, fake_pystray: None) -> tray._Tray:
    return tray._Tray(env.ctx)


@pytest.fixture
def sync_threads(parts: tray._Tray, monkeypatch: pytest.MonkeyPatch) -> tray._Tray:

    def in_thread(name: str, target: Callable[[], object]) -> None:
        parts._guarded(name, target)

    monkeypatch.setattr(parts, "_in_thread", in_thread)
    return parts


@pytest.fixture
def wired(
    sync_threads: tray._Tray, loop_thread: LoopThread
) -> tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event]:
    t = sync_threads
    t._loop = loop_thread.loop
    notifier = RecordingNotifier()
    t._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]
    done = threading.Event()
    original = t._report

    def reporting(*args: Any) -> None:
        try:
            original(*args)
        finally:
            done.set()

    t._report = reporting  # type: ignore[method-assign]  # pyright: ignore[reportAttributeAccessIssue]
    app = FakeApp.last
    return t, app, notifier, done


def write_status(root: Path, payload: Any) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "_status.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )


def status_with(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "service": "running",
        "disk": {"free_gb": 41.2},
        "total_bytes": 2 * 1024**3,
        "chats": [{}, {}],
        "errors": [],
    }
    data.update(overrides)
    return data


# ----------------------------------------------------------------------------- icon image


@pytest.mark.parametrize("state", ["running", "paused", "error"])
def test_icon_image_is_a_transparent_64px_rgba_disc_in_the_state_colour(state: str) -> None:
    image = tray.make_icon_image(state)

    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getpixel((32, 32)) == tray.STATE_COLORS[state]
    assert image.getpixel((0, 0)) == (0, 0, 0, 0)
    assert image.getpixel((63, 63)) == (0, 0, 0, 0)
    assert image.getpixel((12, 32)) == tray.STATE_COLORS[state]
    assert image.getpixel((2, 32)) == (0, 0, 0, 0)


def test_icon_colours_differ_per_state_and_unknown_state_looks_paused() -> None:
    centres = {state: tray.make_icon_image(state).getpixel((32, 32)) for state in tray.STATE_COLORS}

    assert len(set(centres.values())) == 3
    assert tray.make_icon_image("bogus").getpixel((32, 32)) == centres["paused"]


# ----------------------------------------------------------------------------- notifier


def test_notifications_before_attach_are_queued_and_flushed_in_order() -> None:
    notifier = tray.TrayNotifier()
    icon = FakeIcon("n", None, "t", FakeMenu())

    notifier.notify(Level.INFO, "First", "one")
    notifier.notify(Level.INFO, "Second", "two")
    assert icon.toasts == []
    notifier.attach(icon)

    assert icon.toasts == [("one", "First"), ("two", "Second")]
    notifier.notify(Level.INFO, "Third", "three")
    assert icon.toasts[-1] == ("three", "Third")
    other = FakeIcon("n", None, "t", FakeMenu())
    notifier.attach(other)
    assert other.toasts == []


@pytest.mark.parametrize(
    ("level", "prefix", "log_level"),
    [
        (Level.INFO, "", logging.INFO),
        (Level.WARNING, "Warning: ", logging.WARNING),
        (Level.ERROR, "Error: ", logging.ERROR),
    ],
)
def test_notification_title_prefix_and_log_level_follow_the_severity(
    caplog: pytest.LogCaptureFixture, level: Level, prefix: str, log_level: int
) -> None:
    notifier = tray.TrayNotifier()
    icon = FakeIcon("n", None, "t", FakeMenu())
    notifier.attach(icon)

    with caplog.at_level(logging.DEBUG, logger=tray.log.name):
        notifier.notify(level, "Disk", "low space")

    assert icon.toasts == [("low space", f"{prefix}Disk")]
    record = next(r for r in caplog.records if r.name == tray.log.name)
    assert record.levelno == log_level
    assert record.getMessage() == f"{prefix}Disk: low space"


def test_a_failing_toast_is_logged_and_does_not_stop_later_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    notifier = tray.TrayNotifier()
    icon = FakeIcon("n", None, "t", FakeMenu())
    icon.notify_error = RuntimeError("no tray")
    notifier.attach(icon)

    notifier.notify(Level.INFO, "A", "a")

    assert "tray notification failed" in caplog.text
    icon.notify_error = None
    notifier.notify(Level.INFO, "B", "b")
    assert icon.toasts == [("b", "B")]


def test_a_failing_toast_while_flushing_does_not_lose_the_rest() -> None:
    notifier = tray.TrayNotifier()
    icon = FakeIcon("n", None, "t", FakeMenu())
    calls: list[str] = []

    def flaky(message: str, title: str | None = None) -> None:
        calls.append(message)
        if message == "one":
            raise RuntimeError("boom")

    icon.notify = flaky  # type: ignore[method-assign]  # pyright: ignore[reportAttributeAccessIssue]
    notifier.notify(Level.INFO, "1", "one")
    notifier.notify(Level.INFO, "2", "two")

    notifier.attach(icon)

    assert calls == ["one", "two"]


def test_detach_queues_notifications_again_until_the_next_attach() -> None:
    notifier = tray.TrayNotifier()
    icon = FakeIcon("n", None, "t", FakeMenu())
    notifier.attach(icon)
    notifier.detach()

    notifier.notify(Level.WARNING, "Late", "msg")

    assert icon.toasts == []
    again = FakeIcon("n", None, "t", FakeMenu())
    notifier.attach(again)
    assert again.toasts == [("msg", "Warning: Late")]


# ----------------------------------------------------------------------------- menu


def test_menu_has_the_documented_items_in_order(parts: tray._Tray) -> None:
    items = FakeIcon.last.menu.items

    labels = ["---" if item is FakeMenu.SEPARATOR else item.label() for item in items]
    assert labels == [
        "ChatImport \u00b7 starting",
        "---",
        "Open ChatImport folder",
        "Change folder\u2026",
        "Open chat library",
        "---",
        "Recheck edits now",
        "Clean up old messages",
        "Pause",
        "Reload config",
        "Open log",
        "---",
        "Exit",
    ]
    assert items[0].enabled is False
    assert all(item.enabled for item in items[2:] if item is not FakeMenu.SEPARATOR)
    submenu = find_item(FakeIcon.last.menu, "Clean up old messages").action
    assert [item.label() for item in submenu.items] == ["25 %", "50 %", "75 %"]


def test_the_icon_starts_green_with_the_application_name(parts: tray._Tray) -> None:
    icon = FakeIcon.last

    assert icon.name == "chatimport"
    assert icon.title == "ChatImport"
    assert icon.icon.getpixel((32, 32)) == tray.STATE_COLORS["running"]


def test_status_line_and_toggle_text_follow_the_state(parts: tray._Tray, env: Env) -> None:
    status_item = FakeIcon.last.menu.items[0]
    toggle = find_item(FakeIcon.last.menu, "Pause")
    assert status_item.label() == "ChatImport \u00b7 starting"

    write_status(env.ctx.root, status_with())
    parts._paused = True

    assert status_item.label() == "2 chats \u00b7 live \u00b7 2.0 GB \u00b7 41.2 GB free"
    assert toggle.label() == "Resume"


# ------------------------------ status reading


@pytest.mark.parametrize(
    "content",
    ["{not json", "", "[1, 2]", "null", "42", '"text"'],
)
def test_unreadable_or_non_object_status_means_starting(
    parts: tray._Tray, env: Env, content: str
) -> None:
    write_status(env.ctx.root, content)

    assert parts._read_status() is None
    assert parts._status_text() == "ChatImport \u00b7 starting"
    assert parts._current_state() == "running"


def test_status_with_invalid_utf8_or_a_directory_in_its_place_means_starting(
    parts: tray._Tray, env: Env
) -> None:
    env.ctx.root.mkdir(parents=True)
    (env.ctx.root / "_status.json").write_bytes(b"\xff\xfe\x00{")
    assert parts._read_status() is None

    (env.ctx.root / "_status.json").unlink()
    (env.ctx.root / "_status.json").mkdir()
    assert parts._read_status() is None


def test_status_text_joins_the_lines_and_cuts_at_the_tooltip_limit(
    parts: tray._Tray, env: Env
) -> None:
    def text_with_error_of(length: int) -> str:
        write_status(env.ctx.root, status_with(errors=[{"source": "s", "message": "x" * length}]))
        return parts._status_text()

    baseline = len(text_with_error_of(0))
    exact = text_with_error_of(tray.TOOLTIP_LIMIT - baseline)
    over = text_with_error_of(tray.TOOLTIP_LIMIT - baseline + 1)
    far_over = text_with_error_of(500)

    assert len(exact) == tray.TOOLTIP_LIMIT
    assert exact.endswith("x")
    assert len(over) == tray.TOOLTIP_LIMIT
    assert len(far_over) == tray.TOOLTIP_LIMIT
    assert " | error [s]: " in exact


@pytest.mark.parametrize(
    ("failed", "paused", "status", "expected"),
    [
        (False, False, None, "running"),
        (False, False, status_with(), "running"),
        (False, False, status_with(service=None), "running"),
        (False, False, {"chats": []}, "running"),
        (False, False, status_with(errors=[{"source": "a", "message": "b"}]), "error"),
        (False, False, status_with(errors=[]), "running"),
        (False, False, status_with(service="stopped"), "paused"),
        (False, False, status_with(service="starting"), "paused"),
        (False, True, status_with(), "paused"),
        (False, True, None, "paused"),
        (True, False, None, "error"),
        (True, True, status_with(), "error"),
        (False, True, status_with(errors=[{"source": "a", "message": "b"}]), "error"),
        (False, False, status_with(service="stopped", errors=[{"source": "a"}]), "error"),
    ],
)
def test_icon_state_rules(
    parts: tray._Tray,
    env: Env,
    failed: bool,
    paused: bool,
    status: dict[str, Any] | None,
    expected: str,
) -> None:
    parts._failed = failed
    parts._paused = paused
    if status is not None:
        write_status(env.ctx.root, status)

    assert parts._current_state() == expected


# ----------------------------------------------------------------------------- refresh


def test_refresh_swaps_the_image_only_when_the_state_changes(parts: tray._Tray, env: Env) -> None:
    icon = FakeIcon.last
    first_image = icon.icon

    parts._refresh()
    assert icon.icon is first_image
    assert icon.menu_updates == 1

    write_status(env.ctx.root, status_with(errors=[{"source": "w", "message": "bad"}]))
    parts._refresh()

    assert icon.icon is not first_image
    assert icon.icon.getpixel((32, 32)) == tray.STATE_COLORS["error"]
    assert icon.title == "2 chats \u00b7 live \u00b7 2.0 GB \u00b7 41.2 GB free | error [w]: bad"
    assert icon.menu_updates == 2


def test_refresh_survives_a_failing_icon(
    parts: tray._Tray, caplog: pytest.LogCaptureFixture
) -> None:
    FakeIcon.last.update_error = RuntimeError("gone")

    parts._refresh()

    assert "tray refresh failed" in caplog.text


def test_refresh_loop_refreshes_until_stopped(
    parts: tray._Tray, monkeypatch: pytest.MonkeyPatch
) -> None:
    waits = iter([False, False, True])

    def wait(timeout: float) -> bool:
        return next(waits)

    stop = types.SimpleNamespace(wait=wait)
    monkeypatch.setattr(parts, "_stop_refresh", stop)

    parts._refresh_loop()

    assert FakeIcon.last.menu_updates == 2


def test_on_ready_shows_the_icon_flushes_queued_toasts_and_refreshes(parts: tray._Tray) -> None:
    icon = FakeIcon.last
    parts._notifier.notify(Level.INFO, "Early", "queued")

    parts._on_ready(icon)

    assert icon.visible is True
    assert icon.toasts == [("queued", "Early")]
    assert parts._icon_ready.is_set()
    assert icon.menu_updates == 1


# ----------------------------------------------------------------------------- _report


def completed(result: CommandResult | None = None, error: Exception | None = None) -> Future[Any]:
    future: Future[Any] = Future()
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(result)
    return future


def test_report_of_a_failed_command_notifies_the_message_and_changes_nothing(
    parts: tray._Tray,
) -> None:
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    parts._report("pause", completed(CommandResult(False, "no chats")), {}, "ok")

    assert [(n.level, n.message) for n in notifier.notes] == [(Level.ERROR, "no chats")]
    assert parts._paused is False
    assert FakeIcon.last.menu_updates == 0


def test_report_of_a_failed_command_without_message_names_the_command(parts: tray._Tray) -> None:
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    parts._report("recheck", completed(CommandResult(False, "")), {}, None)

    assert notifier.notes[0].message == "recheck failed"


def test_report_of_an_exception_shows_only_the_exception_type(
    parts: tray._Tray, caplog: pytest.LogCaptureFixture
) -> None:
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    parts._report("trim", completed(error=ValueError("secret detail")), {}, None)

    assert [(n.level, n.message) for n in notifier.notes] == [
        (Level.ERROR, "trim failed: ValueError")
    ]
    assert "command trim failed" in caplog.text


@pytest.mark.parametrize(
    ("command", "result_message", "success", "expected_info"),
    [
        ("recheck", "", "Recheck started", ["Recheck started"]),
        ("recheck", "service says hi", "Recheck started", ["service says hi"]),
        ("recheck", "ignored", None, []),
    ],
)
def test_report_of_success_notifies_only_when_a_success_message_exists(
    parts: tray._Tray,
    command: str,
    result_message: str,
    success: str | None,
    expected_info: list[str],
) -> None:
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    parts._report(command, completed(CommandResult(True, result_message)), {}, success)

    assert [n.message for n in notifier.notes if n.level is Level.INFO] == expected_info
    assert FakeIcon.last.menu_updates == 1


def test_report_tracks_pause_resume_and_the_new_root(parts: tray._Tray, tmp_path: Path) -> None:
    ok = completed(CommandResult(True, ""))

    parts._report("pause", ok, {}, None)
    assert parts._paused is True
    parts._report("resume", ok, {}, None)
    assert parts._paused is False

    target = tmp_path / "moved"
    parts._report("set_root", ok, {"path": str(target)}, None)
    assert parts._root == normalize_root(str(target))


# ----------------------------------------------------------------------------- _submit


def test_submit_without_a_loop_says_the_service_is_not_running(parts: tray._Tray) -> None:
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    parts._submit("pause", {})

    assert [(n.level, n.message) for n in notifier.notes] == [
        (Level.ERROR, "The service is not running")
    ]
    assert FakeApp.last.executed == []


def test_submit_on_a_closed_loop_says_the_service_is_not_running(parts: tray._Tray) -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    parts._loop = loop
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    parts._submit("pause", {})

    assert notifier.notes[0].message == "The service is not running"


def test_submit_when_scheduling_fails_is_reported_not_raised(
    parts: tray._Tray, loop_thread: LoopThread, monkeypatch: pytest.MonkeyPatch
) -> None:
    parts._loop = loop_thread.loop
    notifier = RecordingNotifier()
    parts._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    def refuse(coro: Any, loop: Any) -> Any:
        coro.close()
        raise RuntimeError("loop closed")

    monkeypatch.setattr(tray.asyncio, "run_coroutine_threadsafe", refuse)

    parts._submit("pause", {})

    assert notifier.notes[0].message == "The service is not running"


# ------------------------------ menu actions


def click_and_wait(t: tray._Tray, done: threading.Event, label: str) -> None:
    done.clear()
    FakeIcon.last.click(label)
    assert done.wait(5), f"{label} never reported"


def test_recheck_item_runs_recheck_and_confirms(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
) -> None:
    t, app, notifier, done = wired

    click_and_wait(t, done, "Recheck edits now")

    assert app.executed == [("recheck", {})]
    assert [(n.level, n.message) for n in notifier.notes] == [(Level.INFO, "Recheck started")]


def test_reload_config_item_runs_reload_config(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
) -> None:
    t, app, notifier, done = wired

    click_and_wait(t, done, "Reload config")

    assert app.executed == [("reload_config", {})]
    assert notifier.notes[0].message == "Config reloaded"


def test_pause_and_resume_alternate_through_one_menu_item(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
) -> None:
    t, app, notifier, done = wired
    toggle = FakeIcon.last.menu.items[8]

    click_and_wait(t, done, "Pause")
    assert toggle.label() == "Resume"
    assert t._current_state() == "paused"
    click_and_wait(t, done, "Resume")
    assert toggle.label() == "Pause"

    assert app.executed == [("pause", {}), ("resume", {})]
    assert notifier.notes == []


def test_a_failed_pause_leaves_the_toggle_on_pause_and_shows_the_error(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
) -> None:
    t, app, notifier, done = wired
    app.results["pause"] = CommandResult(False, "nothing to pause")

    click_and_wait(t, done, "Pause")

    assert t._paused is False
    assert [(n.level, n.message) for n in notifier.notes] == [(Level.ERROR, "nothing to pause")]


def test_an_exception_in_the_service_command_becomes_an_error_toast(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
) -> None:
    t, app, notifier, done = wired
    app.execute_error = KeyError("hidden")

    click_and_wait(t, done, "Reload config")

    assert notifier.notes[0].level is Level.ERROR
    assert notifier.notes[0].message == "reload_config failed: KeyError"
    assert "hidden" not in notifier.notes[0].message


@pytest.mark.parametrize("pct", [25, 50, 75])
def test_trim_item_confirms_then_sends_the_percentage_for_all_chats(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
    monkeypatch: pytest.MonkeyPatch,
    pct: int,
) -> None:
    t, app, notifier, done = wired
    questions: list[tuple[str, str]] = []

    def yes(title: str, question: str) -> bool:
        questions.append((title, question))
        return True

    monkeypatch.setattr(tray, "_confirm", yes)

    click_and_wait(t, done, f"{pct} %")

    assert app.executed == [("trim", {"pct": pct, "chat": None})]
    assert f"{pct} %" in questions[0][1]
    assert "cannot be undone" in questions[0][1]
    assert notifier.notes[0].message == "Cleanup finished"


def test_declined_trim_sends_nothing(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _t, app, notifier, _ = wired

    def no(title: str, question: str) -> bool:
        return False

    monkeypatch.setattr(tray, "_confirm", no)

    FakeIcon.last.click("50 %")

    assert app.executed == []
    assert notifier.notes == []


@pytest.mark.parametrize(
    ("folder", "move", "expected"),
    [("C:\\Data", True, True), ("C:\\Data", False, False)],
)
def test_change_folder_sends_the_choice_and_remembers_the_new_root(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
    monkeypatch: pytest.MonkeyPatch,
    folder: str,
    move: bool,
    expected: bool,
) -> None:
    t, app, notifier, done = wired
    monkeypatch.setattr(tray, "_choose_folder", lambda: folder)
    monkeypatch.setattr(tray, "_ask_move", lambda: move)

    click_and_wait(t, done, "Change folder\u2026")

    assert app.executed == [("set_root", {"path": folder, "move": expected})]
    assert t._root == normalize_root(folder)
    assert notifier.notes[0].message == "Folder changed"


def test_change_folder_follows_the_service_message_when_it_has_one(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, app, notifier, done = wired
    app.results["set_root"] = CommandResult(True, "Moved 3 files")
    monkeypatch.setattr(tray, "_choose_folder", lambda: "D:\\X")
    monkeypatch.setattr(tray, "_ask_move", lambda: True)

    click_and_wait(t, done, "Change folder\u2026")

    assert notifier.notes[0].message == "Moved 3 files"


def test_failed_folder_change_keeps_the_old_root(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t, app, notifier, done = wired
    before = t._root
    app.results["set_root"] = CommandResult(False, "target is not empty")
    monkeypatch.setattr(tray, "_choose_folder", lambda: "D:\\X")
    monkeypatch.setattr(tray, "_ask_move", lambda: True)

    click_and_wait(t, done, "Change folder\u2026")

    assert t._root == before
    assert notifier.notes[0].message == "target is not empty"


@pytest.mark.parametrize(("chosen", "move"), [("", True), ("", None), ("C:\\Data", None)])
def test_cancelling_a_dialog_changes_nothing(
    wired: tuple[tray._Tray, FakeApp, RecordingNotifier, threading.Event],
    monkeypatch: pytest.MonkeyPatch,
    chosen: str,
    move: bool | None,
) -> None:
    _t, app, notifier, _ = wired
    asked: list[str] = []
    monkeypatch.setattr(tray, "_choose_folder", lambda: chosen)

    def ask() -> bool | None:
        asked.append("move")
        return move

    monkeypatch.setattr(tray, "_ask_move", ask)

    FakeIcon.last.click("Change folder\u2026")

    assert app.executed == []
    assert notifier.notes == []
    assert bool(asked) is bool(chosen)


# ------------------------------ opening things


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    paths: list[Path] = []
    monkeypatch.setattr(tray, "_open_path", paths.append)
    return paths


def test_open_root_creates_a_missing_folder_and_opens_it(
    sync_threads: tray._Tray, env: Env, opened: list[Path]
) -> None:
    assert not env.ctx.root.exists()

    FakeIcon.last.click("Open ChatImport folder")

    assert env.ctx.root.is_dir()
    assert opened == [env.ctx.root]


def test_open_library_creates_an_empty_file_only_when_missing(
    sync_threads: tray._Tray, env: Env, opened: list[Path]
) -> None:
    library = env.ctx.library_file

    FakeIcon.last.click("Open chat library")
    assert library.read_bytes() == b""

    library.write_text('[[chat]]\nref = "@keep"\n', encoding="utf-8")
    FakeIcon.last.click("Open chat library")

    assert library.read_text(encoding="utf-8") == '[[chat]]\nref = "@keep"\n'
    assert opened == [library, library]


def test_open_library_creates_missing_parent_folders(
    env: Env, fake_pystray: None, opened: list[Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = env.home / "deep" / "er" / "chats.toml"
    ctx = types.SimpleNamespace(
        root=env.ctx.root, library_file=nested, paths=env.ctx.paths, config=env.ctx.config
    )
    t = tray._Tray(ctx)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]

    def in_thread(name: str, target: Callable[[], object]) -> None:
        t._guarded(name, target)

    monkeypatch.setattr(t, "_in_thread", in_thread)

    FakeIcon.last.click("Open chat library")

    assert nested.is_file()


def test_open_log_picks_the_newest_file(
    sync_threads: tray._Tray, env: Env, opened: list[Path]
) -> None:
    logs = env.ctx.paths.log_dir
    old, new = logs / "chatimport.log.1", logs / "chatimport.log"
    for path, stamp in ((old, 1_000_000), (new, 2_000_000)):
        path.write_text("x", encoding="utf-8")
        os.utime(path, (stamp, stamp))
    (logs / "sub").mkdir()
    os.utime(logs / "sub", (3_000_000, 3_000_000))

    FakeIcon.last.click("Open log")

    assert opened == [new]


def test_open_log_without_logs_tells_the_user(sync_threads: tray._Tray, opened: list[Path]) -> None:
    notifier = RecordingNotifier()
    sync_threads._notifier = notifier  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]

    FakeIcon.last.click("Open log")

    assert opened == []
    assert [(n.level, n.message) for n in notifier.notes] == [
        (Level.INFO, "There is no log file yet")
    ]


def test_latest_file_edge_cases(tmp_path: Path) -> None:
    assert tray._latest_file(tmp_path / "missing") is None
    assert tray._latest_file(tmp_path) is None
    (tmp_path / "only-dir").mkdir()
    assert tray._latest_file(tmp_path) is None
    only = tmp_path / "a.log"
    only.write_text("1", encoding="utf-8")
    assert tray._latest_file(tmp_path) == only


def test_latest_file_ignores_a_file_that_disappears_while_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keep, gone = tmp_path / "keep.log", tmp_path / "gone.log"
    keep.write_text("1", encoding="utf-8")
    gone.write_text("1", encoding="utf-8")
    real_is_file = type(keep).is_file

    def vanishing(self: Path, **kwargs: Any) -> bool:
        result = real_is_file(self, **kwargs)
        if self.name == "gone.log":
            self.unlink()
        return result

    monkeypatch.setattr(type(keep), "is_file", vanishing)

    assert tray._latest_file(tmp_path) == keep


@pytest.mark.parametrize(("platform", "opener"), [("linux", "xdg-open"), ("darwin", "open")])
def test_open_path_uses_the_platform_opener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, opener: str
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "platform", platform)

    def popen(argv: list[str]) -> None:
        calls.append(argv)

    monkeypatch.setattr(tray.subprocess, "Popen", popen)

    tray._open_path(tmp_path)

    assert calls == [[opener, str(tmp_path)]]


def test_open_path_on_windows_uses_startfile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started: list[Path] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(tray.os, "startfile", started.append, raising=False)

    tray._open_path(tmp_path)

    assert started == [tmp_path]


# ------------------------------ guarded / threads


def test_guarded_logs_an_action_failure_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom() -> None:
        raise OSError("disk")

    tray._Tray._guarded("open", boom)

    assert "tray action open failed" in caplog.text


def test_in_thread_runs_the_target_off_the_calling_thread(parts: tray._Tray) -> None:
    seen: list[str] = []
    done = threading.Event()

    def work() -> None:
        seen.append(threading.current_thread().name)
        done.set()

    parts._in_thread("x", work)

    assert done.wait(5)
    assert seen[0] != threading.current_thread().name


# ----------------------------------------------------------------------------- tk dialogs


class FakeRoot:
    instances: list[FakeRoot] = []  # noqa: RUF012

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        FakeRoot.instances.append(self)

    def withdraw(self) -> None:
        self.calls.append(("withdraw", None))

    def attributes(self, *args: Any) -> None:
        self.calls.append(("attributes", args))

    def destroy(self) -> None:
        self.calls.append(("destroy", None))


@pytest.fixture
def fake_tk(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    FakeRoot.instances = []

    def yes(*args: Any, **kwargs: Any) -> bool:
        return True

    def picked(**kwargs: Any) -> str:
        return "C:/picked"

    messagebox = types.SimpleNamespace(askyesno=yes, askyesnocancel=yes)
    filedialog = types.SimpleNamespace(askdirectory=picked)
    module = types.ModuleType("tkinter")
    module.Tk = FakeRoot  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    module.messagebox = messagebox  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    module.filedialog = filedialog  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "tkinter", module)
    return types.SimpleNamespace(messagebox=messagebox, filedialog=filedialog)


@pytest.mark.parametrize("answer", [True, False])
def test_confirm_returns_the_answer_and_destroys_the_hidden_root(
    fake_tk: types.SimpleNamespace, answer: bool
) -> None:
    seen: dict[str, Any] = {}

    def ask(title: str, question: str, parent: Any) -> bool:
        seen.update(title=title, question=question, parent=parent)
        return answer

    fake_tk.messagebox.askyesno = ask

    assert tray._confirm("T", "Q?") is answer

    root = FakeRoot.instances[0]
    assert seen["parent"] is root
    assert (seen["title"], seen["question"]) == ("T", "Q?")
    assert [name for name, _ in root.calls] == ["withdraw", "attributes", "destroy"]
    assert ("attributes", ("-topmost", True)) in root.calls


def test_confirm_destroys_the_root_even_when_the_dialog_fails(
    fake_tk: types.SimpleNamespace,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("tk")

    fake_tk.messagebox.askyesno = broken

    with pytest.raises(RuntimeError):
        tray._confirm("T", "Q?")

    assert FakeRoot.instances[0].calls[-1] == ("destroy", None)


@pytest.mark.parametrize(("picked", "expected"), [("C:/picked", "C:/picked"), ("", "")])
def test_choose_folder_returns_the_path_or_an_empty_string_on_cancel(
    fake_tk: types.SimpleNamespace, picked: str, expected: str
) -> None:

    def ask(**kwargs: Any) -> str:
        return picked

    fake_tk.filedialog.askdirectory = ask

    assert tray._choose_folder() == expected
    assert FakeRoot.instances[0].calls[-1] == ("destroy", None)


@pytest.mark.parametrize(("answer", "expected"), [(True, True), (False, False), (None, None)])
def test_ask_move_maps_yes_no_cancel(
    fake_tk: types.SimpleNamespace, answer: bool | None, expected: bool | None
) -> None:
    captured: dict[str, Any] = {}

    def ask(title: str, text: str, parent: Any) -> bool | None:
        captured["text"] = text
        return answer

    fake_tk.messagebox.askyesnocancel = ask

    assert tray._ask_move() is expected
    assert "Cancel" in captured["text"]
    assert FakeRoot.instances[0].calls[-1] == ("destroy", None)


# ------------------------------ run_tray orchestration


def test_exit_item_stops_the_service_joins_it_and_stops_the_icon(
    env: Env, fake_pystray: None
) -> None:
    def script(icon: FakeIcon) -> None:
        assert FakeApp.last.running.wait(5)
        assert icon.visible
        icon.click("Exit")

    FakeIcon.script = script

    tray.run_tray(env.ctx)

    assert FakeIcon.last.stopped.is_set()
    assert FakeApp.last.shutdown_calls == 1
    assert wait_until(
        lambda: not any(t.name == "chatimport-service" for t in threading.enumerate())
    )


def test_the_service_gets_the_tray_notifier_and_the_context(env: Env, fake_pystray: None) -> None:
    FakeIcon.script = lambda icon: icon.click("Exit")

    tray.run_tray(env.ctx)

    assert FakeApp.last.ctx is env.ctx
    assert isinstance(FakeApp.last.notifier, tray.TrayNotifier)


def test_a_second_instance_tells_the_user_and_closes_the_icon(
    env: Env, fake_pystray: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tray, "ALREADY_RUNNING_LINGER_SECONDS", 0)
    original_init = FakeApp.__init__

    def init(self: FakeApp, ctx: Any, *, notifier: Any) -> None:
        original_init(self, ctx, notifier=notifier)
        self.run_error = AlreadyRunning("another instance")

    monkeypatch.setattr(FakeApp, "__init__", init)

    tray.run_tray(env.ctx)

    assert FakeIcon.last.toasts == [("ChatImport is already running", "ChatImport")]
    assert FakeIcon.last.stopped.is_set()
    assert FakeIcon.last.visible


def test_a_crashed_service_shows_only_the_exception_type_and_keeps_the_tray(
    env: Env, fake_pystray: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    original_init = FakeApp.__init__

    def init(self: FakeApp, ctx: Any, *, notifier: Any) -> None:
        original_init(self, ctx, notifier=notifier)
        self.run_error = RuntimeError("api_hash=SECRET-VALUE")

    monkeypatch.setattr(FakeApp, "__init__", init)

    def script(icon: FakeIcon) -> None:
        assert wait_until(lambda: icon.toasts)
        assert wait_until(lambda: icon.icon.getpixel((32, 32)) == tray.STATE_COLORS["error"])
        assert not icon.stopped.is_set()
        icon.click("Exit")

    FakeIcon.script = script

    tray.run_tray(env.ctx)

    assert FakeIcon.last.toasts == [
        ("The service failed: RuntimeError", "Error: ChatImport stopped")
    ]
    assert "SECRET-VALUE" not in repr(FakeIcon.last.toasts)
    assert "the ChatImport service stopped" in caplog.text


def test_a_service_that_returns_normally_closes_the_icon(
    env: Env, fake_pystray: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_init = FakeApp.__init__

    def init(self: FakeApp, ctx: Any, *, notifier: Any) -> None:
        original_init(self, ctx, notifier=notifier)
        self.returns_immediately = True

    monkeypatch.setattr(FakeApp, "__init__", init)

    tray.run_tray(env.ctx)

    assert FakeIcon.last.stopped.is_set()


def test_the_service_loop_is_closed_after_the_service_ends(env: Env, fake_pystray: None) -> None:
    holder: list[tray._Tray] = []
    original = tray._Tray.__init__

    def capture(self: tray._Tray, ctx: Any) -> None:
        original(self, ctx)
        holder.append(self)

    FakeIcon.script = lambda icon: icon.click("Exit")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(tray._Tray, "__init__", capture)
        tray.run_tray(env.ctx)

    loop = holder[0]._loop
    assert loop is not None
    assert wait_until(loop.is_closed)


def test_exit_while_the_service_ignores_the_shutdown_request_logs_and_still_stops(
    env: Env,
    fake_pystray: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(tray, "SERVICE_JOIN_SECONDS", 0.05)
    original_init = FakeApp.__init__

    def init(self: FakeApp, ctx: Any, *, notifier: Any) -> None:
        original_init(self, ctx, notifier=notifier)
        self.ignore_shutdown = True

    monkeypatch.setattr(FakeApp, "__init__", init)

    def script(icon: FakeIcon) -> None:
        assert FakeApp.last.running.wait(5)
        icon.click("Exit")

    FakeIcon.script = script

    tray.run_tray(env.ctx)
    FakeApp.last.force_stop()

    assert FakeIcon.last.stopped.is_set()
    assert "did not stop within" in caplog.text


def test_closing_the_tray_window_without_the_exit_item_still_shuts_the_service_down(
    env: Env, fake_pystray: None
) -> None:
    def script(icon: FakeIcon) -> None:
        assert FakeApp.last.running.wait(5)
        icon.stop()

    FakeIcon.script = script

    tray.run_tray(env.ctx)

    assert FakeApp.last.shutdown_calls == 1
