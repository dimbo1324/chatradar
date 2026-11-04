from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING, Any

from chatimport.commands import CommandResult
from chatimport.gui.pages import data_cleanup
from chatimport.trim import TrimPreview
from tests.unit.gui.pages_b.archive import ALPHA_ID, BETA_ID

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from chatimport.gui.pages.data import DataPage
    from tests.unit.gui.conftest import FakeBridge
    from tests.unit.gui.pages_b.conftest import Answers, Toasts

type Settle = Callable[[Callable[[], bool]], None]


def loaded(page: DataPage, settle: Settle) -> None:
    page.calculate()
    settle(lambda: page.env.usage is not None and not page._calculating)  # pyright: ignore[reportPrivateUsage]


def previewed(page: DataPage, settle: Settle) -> None:
    page.cleanup.preview()
    settle(lambda: not page.cleanup._busy)  # pyright: ignore[reportPrivateUsage]


def failing(bridge: FakeBridge) -> None:
    def execute(command: str, args: dict[str, Any] | None = None) -> Future[CommandResult]:
        future: Future[CommandResult] = Future()
        future.set_exception(RuntimeError("down"))
        return future

    bridge.execute = execute  # type: ignore[method-assign]


def test_preview_then_cancel_and_confirm(
    data_page: DataPage, settle: Settle, bridge: FakeBridge, answers: Answers, toasts: Toasts
) -> None:
    card = data_page.cleanup
    loaded(data_page, settle)
    assert card.chat.count() == 3
    assert card.selected_pct() == 50
    assert not card.run_button.isEnabled()
    card.run()
    assert bridge.calls == []
    previewed(data_page, settle)
    assert card.model.rowCount() == 2
    assert card.run_button.isEnabled()
    card.preview_button.click()
    settle(lambda: not card._busy)  # pyright: ignore[reportPrivateUsage]
    answers.accept = False
    card.run_button.click()
    assert answers.asked
    assert bridge.calls == []
    answers.accept = True
    bridge.replies["trim"] = CommandResult(True, data={"records": 3, "bytes": 2048})
    card.run()
    assert bridge.calls == [("trim", {"pct": 50})]
    assert toasts.tones() == ["success"]
    assert card.model.rowCount() == 0
    assert not card.run_button.isEnabled()


def test_trim_one_chat(
    data_page: DataPage, settle: Settle, bridge: FakeBridge, answers: Answers
) -> None:
    card = data_page.cleanup
    loaded(data_page, settle)
    card.chat.setCurrentIndex(card.chat.findData(ALPHA_ID))
    card.share.selected.emit("75")
    previewed(data_page, settle)
    assert card.model.rowCount() == 1
    card.run()
    assert bridge.calls == [("trim", {"pct": 50, "chat": ALPHA_ID})]
    assert card._scope() == "Alpha"  # pyright: ignore[reportPrivateUsage]


def test_changing_selection_invalidates_preview(data_page: DataPage, settle: Settle) -> None:
    card = data_page.cleanup
    loaded(data_page, settle)
    previewed(data_page, settle)
    card.share.selected.emit("25")
    assert card.model.rowCount() == 0
    assert not card.table.isVisibleTo(data_page)
    card._invalidate()  # pyright: ignore[reportPrivateUsage]
    assert BETA_ID in [pair[0] for pair in data_page.env.chats()]


def test_preview_failure_and_busy_guard(
    data_page: DataPage,
    settle: Settle,
    toasts: Toasts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = data_page.cleanup

    def boom(*_args: object) -> TrimPreview:
        raise OSError("x")

    monkeypatch.setattr(data_cleanup, "preview_percent", boom)
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    card.preview()
    card._busy = False  # pyright: ignore[reportPrivateUsage]
    assert toasts.items == []
    card.preview()
    settle(lambda: bool(toasts.items))
    assert toasts.tones() == ["danger"]
    card.run()


def test_nothing_to_remove(
    data_page: DataPage,
    settle: Settle,
    bridge: FakeBridge,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = data_page.cleanup

    def empty(*_args: object) -> TrimPreview:
        return TrimPreview(25, ())

    monkeypatch.setattr(data_cleanup, "preview_percent", empty)
    previewed(data_page, settle)
    assert not card.run_button.isEnabled()
    assert card.summary.text()
    card.run()
    assert bridge.calls == []


def test_run_while_busy_is_ignored(data_page: DataPage, settle: Settle, bridge: FakeBridge) -> None:
    card = data_page.cleanup
    loaded(data_page, settle)
    previewed(data_page, settle)
    card._busy = True  # pyright: ignore[reportPrivateUsage]
    card.run()
    assert bridge.calls == []
    card._busy = False  # pyright: ignore[reportPrivateUsage]


def test_trim_unavailable_and_failed(
    data_page: DataPage,
    settle: Settle,
    bridge: FakeBridge,
    answers: Answers,
    toasts: Toasts,
) -> None:
    card = data_page.cleanup
    loaded(data_page, settle)
    previewed(data_page, settle)
    bridge.replies["trim"] = CommandResult(False, "no")
    card.run()
    assert toasts.tones() == ["danger"]
    failing(bridge)
    card.run()
    assert toasts.tones() == ["danger", "warning"]


def test_trim_result_without_numbers(
    data_page: DataPage, settle: Settle, bridge: FakeBridge, answers: Answers, toasts: Toasts
) -> None:
    card = data_page.cleanup
    loaded(data_page, settle)
    previewed(data_page, settle)
    bridge.replies["trim"] = CommandResult(True, data={"records": "x"})
    card.run()
    assert toasts.tones() == ["success"]


def test_language_switch(data_page: DataPage, settle: Settle, gui: Any) -> None:
    loaded(data_page, settle)
    previewed(data_page, settle)
    gui.language.set_language("ru")
    gui.language.set_language("en")
    assert data_page.cleanup.summary.text()
