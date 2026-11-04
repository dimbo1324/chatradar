from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

from chatimport.commands import CommandResult
from chatimport.gui.models.snapshot import parse_chat
from chatimport.gui.pages import chats_actions as actions_module
from chatimport.gui.pages.chats_actions import ChatActions

from .conftest import chat

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from chatimport.gui.context import GuiContext
    from chatimport.gui.models.snapshot import ChatRow
    from tests.unit.gui.conftest import FakeBridge

Toasts = list[tuple[str, str]]


def row(chat_id: int, **extra: Any) -> ChatRow:
    parsed = parse_chat(chat(chat_id, **extra))
    assert parsed is not None
    return parsed


@pytest.fixture
def toasts(monkeypatch: pytest.MonkeyPatch) -> Toasts:
    seen: Toasts = []

    def record(_widget: QWidget, tone: str, text: str) -> None:
        seen.append((tone, text))

    monkeypatch.setattr(actions_module, "notify", record)
    return seen


@pytest.fixture
def actions(gui: GuiContext, toasts: Toasts) -> Iterator[ChatActions]:
    page = QWidget()
    built = ChatActions(gui, page)
    yield built
    built._runner._pool.shutdown(wait=True)
    page.deleteLater()


def answer_dialog(index: int) -> None:
    def click() -> None:
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        box.buttons()[index].click()

    QTimer.singleShot(0, click)


def found(folder: Path | None) -> Callable[[Path, int], Path | None]:
    def finder(_root: Path, _chat_id: int) -> Path | None:
        return folder

    return finder


def pump(condition: Callable[[], bool]) -> None:
    for _ in range(100):
        if condition():
            return
        QTest.qWait(20)
    raise AssertionError("condition not reached")


def test_simple_commands_send_one_call_per_row(
    actions: ChatActions, bridge: FakeBridge, toasts: Toasts
) -> None:
    rows = [row(1), row(2)]
    actions.recheck(rows)
    actions.deeper(rows)
    assert [c[0] for c in bridge.calls] == ["recheck", "recheck", "deeper", "deeper"]
    assert bridge.calls[0][1] == {"chat": 1}
    assert [t[0] for t in toasts] == ["success", "success"]


def test_pause_skips_paused_rows_and_falls_back(actions: ChatActions, bridge: FakeBridge) -> None:
    paused = row(2, paused=True)
    actions.pause([row(1), paused])
    assert [c[1]["chat"] for c in bridge.calls] == [1]
    bridge.calls.clear()
    actions.pause([paused])
    assert [c[1]["chat"] for c in bridge.calls] == [2]


def test_resume_picks_paused_rows_and_falls_back(actions: ChatActions, bridge: FakeBridge) -> None:
    actions.resume([row(1), row(2, paused=True)])
    assert [c[1]["chat"] for c in bridge.calls] == [2]
    bridge.calls.clear()
    actions.resume([row(1)])
    assert [c[1]["chat"] for c in bridge.calls] == [1]


def test_empty_selection_sends_nothing(
    actions: ChatActions, bridge: FakeBridge, toasts: Toasts
) -> None:
    actions.recheck([])
    assert bridge.calls == []
    assert toasts == []


def test_failed_command_toasts_danger(
    actions: ChatActions, bridge: FakeBridge, toasts: Toasts
) -> None:
    bridge.replies["recheck"] = CommandResult(False, "no")
    actions.recheck([row(1)])
    assert [t[0] for t in toasts] == ["danger"]


def test_unavailable_service_toasts_warning(
    actions: ChatActions, bridge: FakeBridge, toasts: Toasts, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    monkeypatch.setattr(bridge, "execute", broken)
    actions.recheck([row(1), row(2)])
    assert [t[0] for t in toasts] == ["warning"]


def test_mixed_results_report_success(
    actions: ChatActions, bridge: FakeBridge, toasts: Toasts, monkeypatch: pytest.MonkeyPatch
) -> None:
    results = iter([CommandResult(True), CommandResult(False)])

    def execute(command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_result(next(results))
        return future

    monkeypatch.setattr(bridge, "execute", execute)
    actions.recheck([row(1), row(2)])
    assert [t[0] for t in toasts] == ["success"]


@pytest.mark.parametrize("index", [0, 1])
def test_refetch_asks_first(
    actions: ChatActions, bridge: FakeBridge, toasts: Toasts, index: int
) -> None:
    answer_dialog(index)
    actions.refetch([row(1), row(2)])
    sent = [c[0] for c in bridge.calls]
    assert sent == (["refetch", "refetch"] if index == 0 else [])


@pytest.mark.parametrize("index", [0, 1])
def test_trim_asks_first_and_sends_percent(
    actions: ChatActions, bridge: FakeBridge, index: int
) -> None:
    answer_dialog(index)
    actions.trim([row(1)], 50)
    assert bridge.calls == ([("trim", {"chat": 1, "pct": 50})] if index == 0 else [])


def test_open_folder_opens_the_found_folder(
    actions: ChatActions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url.toLocalFile())
        return True

    monkeypatch.setattr(actions_module, "find_chat_folder", found(tmp_path))
    monkeypatch.setattr(actions_module.QDesktopServices, "openUrl", open_url)
    actions.open_folder(row(1))
    pump(lambda: bool(opened))
    assert [Path(p) for p in opened] == [tmp_path]


@pytest.mark.parametrize("failure", ["missing", "error"])
def test_open_folder_without_a_folder_warns(
    actions: ChatActions, toasts: Toasts, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def finder(_root: Path, _id: int) -> Path | None:
        if failure == "error":
            raise OSError("disk")
        return None

    monkeypatch.setattr(actions_module, "find_chat_folder", finder)
    actions.open_folder(row(1))
    pump(lambda: bool(toasts))
    assert [t[0] for t in toasts] == ["warning"]


def test_export_success(
    actions: ChatActions, toasts: Toasts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def export(folder: Path, *, include_names: bool) -> Path:
        calls.append(include_names)
        return folder / "out.json"

    monkeypatch.setattr(actions_module, "find_chat_folder", found(tmp_path))
    monkeypatch.setattr(actions_module, "export_chat_json", export)
    actions.export(row(1))
    pump(lambda: bool(toasts))
    assert calls == [False]
    assert toasts[0][0] == "success"


def test_export_without_a_folder_warns(
    actions: ChatActions, toasts: Toasts, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(actions_module, "find_chat_folder", found(None))
    actions.export(row(1))
    pump(lambda: bool(toasts))
    assert [t[0] for t in toasts] == ["warning"]


def test_export_failure_reports_danger(
    actions: ChatActions, toasts: Toasts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_folder: Path, *, include_names: bool) -> Path:
        raise OSError("full")

    monkeypatch.setattr(actions_module, "find_chat_folder", found(tmp_path))
    monkeypatch.setattr(actions_module, "export_chat_json", broken)
    actions.export(row(1))
    pump(lambda: bool(toasts))
    assert [t[0] for t in toasts] == ["danger"]


def test_menu_for_one_row_enables_everything(actions: ChatActions) -> None:
    menu = actions.build_menu([row(1)])
    enabled = [a.isEnabled() for a in menu.actions() if not a.isSeparator()]
    assert all(enabled)
    assert len(enabled) == 8


def test_menu_for_many_rows_disables_single_row_items(actions: ChatActions) -> None:
    menu = actions.build_menu([row(1), row(2)], actions._page)
    plain = [a for a in menu.actions() if not a.isSeparator() and not a.menu()]
    assert [a.isEnabled() for a in plain] == [True, True, True, True, True, False, False]


def test_menu_for_no_rows_is_disabled(actions: ChatActions) -> None:
    menu = actions.build_menu([])
    assert not any(a.isEnabled() for a in menu.actions() if not a.isSeparator())


def test_menu_actions_trigger_commands(
    actions: ChatActions, bridge: FakeBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder_calls: list[int] = []
    export_calls: list[int] = []

    def fake_open(target: ChatRow) -> None:
        folder_calls.append(target.chat_id)

    def fake_export(target: ChatRow) -> None:
        export_calls.append(target.chat_id)

    monkeypatch.setattr(actions, "open_folder", fake_open)
    monkeypatch.setattr(actions, "export", fake_export)
    answer_dialog(0)
    menu = actions.build_menu([row(5)])
    for item in menu.actions():
        if item.isSeparator():
            continue
        sub = item.menu()
        if not isinstance(sub, QMenu):
            if item.text() == actions_module.tr("chats.act.refetch"):
                answer_dialog(0)
            item.trigger()
        else:
            answer_dialog(0)
            sub.actions()[0].trigger()
    sent = {call[0] for call in bridge.calls}
    assert {"pause", "resume", "recheck", "deeper", "refetch", "trim"} <= sent
    assert folder_calls == [5]
    assert export_calls == [5]
