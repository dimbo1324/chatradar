from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from chatimport.commands import CommandResult

if TYPE_CHECKING:
    from chatimport.gui.pages.data import DataPage
    from tests.unit.gui.conftest import FakeBridge
    from tests.unit.gui.pages_b.conftest import Answers, Toasts

ISSUES = {
    "issues": [
        {"severity": "error", "folder": "alpha", "message": "bad part"},
        {"severity": "warning", "folder": "beta", "message": "stale temp"},
        "junk",
    ]
}


def test_check_lists_issues_then_repairs(
    data_page: DataPage, bridge: FakeBridge, answers: Answers, toasts: Toasts
) -> None:
    card = data_page.integrity
    assert not card.repair_button.isEnabled()
    card.repair()
    assert bridge.calls == []
    bridge.replies["check"] = CommandResult(True, data=ISSUES)
    card.run_button.click()
    assert bridge.calls == [("check", {"repair": False})]
    assert card.model.rowCount() == 2
    assert card.repair_button.isEnabled()
    answers.accept = False
    card.repair_button.click()
    assert len(bridge.calls) == 1
    answers.accept = True
    bridge.replies["check"] = CommandResult(True, data={"issues": []})
    card.repair()
    assert bridge.calls[-1] == ("check", {"repair": True})
    assert toasts.tones() == ["success"]
    data_page.show()
    assert card.ok.isVisibleTo(data_page)
    assert not card.repair_button.isEnabled()


def test_check_failure_modes(data_page: DataPage, bridge: FakeBridge, toasts: Toasts) -> None:
    card = data_page.integrity
    bridge.replies["check"] = CommandResult(False, "no")
    card.run_check()
    assert toasts.tones() == ["danger"]

    def execute(command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    bridge.execute = execute  # type: ignore[method-assign]
    card.run_check()
    assert toasts.tones() == ["danger", "warning"]


def test_busy_blocks_new_checks(data_page: DataPage, bridge: FakeBridge) -> None:
    card = data_page.integrity
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    card.run_check()
    card._rows = []  # pyright: ignore[reportPrivateUsage]
    card.repair()
    card._rows = [object()]  # type: ignore[list-item]  # pyright: ignore[reportPrivateUsage]
    card.repair()
    assert bridge.calls == []
    card._rows = None  # pyright: ignore[reportPrivateUsage]
    card._busy = False  # pyright: ignore[reportPrivateUsage]
    card.retranslate()


def test_repair_from_real_check_report(
    data_page: DataPage, bridge: FakeBridge, answers: Answers
) -> None:
    from datetime import UTC, datetime

    from chatimport.integrity import check_root

    folder = next(data_page.env.root.glob("alpha_*"))
    next(folder.glob("*.jsonl")).write_text("not json\n", encoding="utf-8")
    found = check_root(data_page.env.root, repair=False, now=datetime.now(UTC))
    rows = [{"severity": i.severity, "folder": i.folder, "message": i.message} for i in found]
    assert rows
    bridge.replies["check"] = CommandResult(True, data={"issues": rows})
    data_page.integrity.run_check()
    assert data_page.integrity.model.rowCount() == len(rows)
