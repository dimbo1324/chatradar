from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QItemSelectionModel, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QMenu

from chatimport.gui.pages import log as log_module
from chatimport.gui.pages.log import EMPTY, LOADING, MISSING, NO_MATCHES, TABLE, LogPage
from chatimport.logging_setup import LOG_FILE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from chatimport.gui.context import GuiContext
    from tests.unit.gui.pages_b.conftest import Clipboard, Opened, Toasts

type Settle = Callable[[Callable[[], bool]], None]

TRACE = "Traceback (most recent call last):\n  File x\nValueError: boom"


def line(second: int, level: str, logger: str, message: str, minute: int = 0) -> str:
    return f"2026-10-31T20:{minute:02d}:{second:02d}.001Z {level} {logger}: {message}\n"


def sample() -> str:
    return (
        line(1, "DEBUG", "chatimport.worker", "quiet detail")
        + line(2, "INFO", "chatimport.worker", "backfill started")
        + line(3, "WARNING", "chatimport.router", "slow down")
        + line(4, "ERROR", "chatimport.worker", "failed hard")
        + TRACE
        + "\n"
        + line(5, "CRITICAL", "chatimport.app", "fatal stop")
    )


@pytest.fixture
def log_file(gui: GuiContext) -> Path:
    return gui.service.paths.log_dir / LOG_FILE


def open_page(gui: GuiContext, settle: Settle) -> LogPage:
    page = LogPage(gui)
    page.resize(1000, 700)
    page.show()
    settle(lambda: page.source.ready)
    return page


def test_missing_file(gui: GuiContext, settle: Settle) -> None:
    page = LogPage(gui)
    assert page.stack.currentIndex() == LOADING
    page.show()
    settle(lambda: page.source.ready)
    assert page.stack.currentIndex() == MISSING
    assert page.missing_path.text()
    assert not page.older_button.isEnabled() or page.source.has_older
    page.hide()


def test_empty_file(gui: GuiContext, settle: Settle, log_file: Path) -> None:
    log_file.write_text("", encoding="utf-8")
    page = open_page(gui, settle)
    assert page.stack.currentIndex() == EMPTY
    page.copy_lines()
    page.hide()


def test_filters(gui: GuiContext, settle: Settle, log_file: Path) -> None:
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    assert page.stack.currentIndex() == TABLE
    assert page.model.rowCount() == 5
    assert (page.model.warnings, page.model.errors) == (1, 2)
    assert page.sources.count() == 4
    page.levels.selected.emit("error")
    assert page.proxy.rowCount() == 2
    page.levels.selected.emit("all")
    page.sources.setCurrentIndex(page.sources.findData("chatimport.router"))
    assert page.proxy.rowCount() == 1
    page.sources.setCurrentIndex(0)
    page.search.query_changed.emit("backfill")
    assert page.proxy.rowCount() == 1
    page.search.query_changed.emit("zzz")
    assert page.stack.currentIndex() == NO_MATCHES
    page.search.query_changed.emit("")
    page.traceback_switch.set_checked(False)
    assert page.proxy.rowCount() == 4
    page.traceback_switch.set_checked(True)
    page.focus_search()
    page.hide()


def test_detail_and_copy(
    gui: GuiContext, settle: Settle, log_file: Path, clipboard: Clipboard, toasts: Toasts
) -> None:
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    page.copy_lines()
    assert clipboard.text.count("\n") >= 5
    page.table.selectRow(3)
    assert "Traceback" in page.detail.toPlainText()
    page.copy_lines()
    assert clipboard.text.startswith("2026-10-31T20:00:04.001Z ERROR chatimport.worker")
    page.table.selectionModel().clearSelection()
    page.table.selectionModel().setCurrentIndex(
        page.proxy.index(0, 0), QItemSelectionModel.SelectionFlag.NoUpdate
    )
    assert page.detail.toPlainText() == ""
    assert toasts.tones().count("success") == 2
    page.hide()


def test_clear_and_open(
    gui: GuiContext,
    settle: Settle,
    log_file: Path,
    opened: Opened,
    toasts: Toasts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    page.clear_view()
    assert page.model.rowCount() == 0
    assert not page.older_button.isEnabled()
    page.open_file()
    page.open_folder()
    assert opened.urls == [str(log_file), str(log_file.parent)]
    opened.ok = False
    page.open_file()
    assert toasts.tones()[-1] == "warning"

    class Menu(QMenu):
        def exec(self, *_args: object) -> None:  # type: ignore[override]
            for action in self.actions():
                action.trigger()

    monkeypatch.setattr(log_module, "QMenu", Menu)
    opened.urls.clear()
    opened.ok = True
    page.open_button.click()
    assert opened.urls == [str(log_file), str(log_file.parent)]
    page.hide()


def test_live_tail_and_rotation(
    gui: GuiContext, settle: Settle, log_file: Path, toasts: Toasts
) -> None:
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(line(6, "INFO", "chatimport.new", "fresh one", minute=1))
    page.source._poll()  # pyright: ignore[reportPrivateUsage]
    assert page.model.rowCount() == 6
    assert page.sources.count() == 5
    log_file.rename(log_file.with_name(LOG_FILE + ".1"))
    log_file.write_text(line(7, "INFO", "chatimport.after", "after rotation", minute=2), "utf-8")
    page.source._poll()  # pyright: ignore[reportPrivateUsage]
    assert "info" in toasts.tones()
    log_file.unlink()
    page.source._poll()  # pyright: ignore[reportPrivateUsage]
    page.source._poll()  # pyright: ignore[reportPrivateUsage]
    page.hide()
    page.source._poll()  # pyright: ignore[reportPrivateUsage]
    page.show()


def test_follow_scroll_and_wrap(gui: GuiContext, settle: Settle, log_file: Path) -> None:
    lines = "".join(
        line(i % 60, "INFO", "chatimport.worker", f"message number {i} " + "word " * 40, i // 60)
        for i in range(150)
    )
    log_file.write_text(lines, encoding="utf-8")
    page = open_page(gui, settle)
    settle(lambda: not page._end_pending)  # pyright: ignore[reportPrivateUsage]
    bar = page.table.verticalScrollBar()
    assert page.follow_switch.is_checked()
    bar.setValue(0)
    assert not page.follow_switch.is_checked()
    assert page.jump.isVisibleTo(page)
    page.wrap_switch.set_checked(True)
    page._on_width_settled()  # pyright: ignore[reportPrivateUsage]
    page.table.horizontalHeader().sectionResized.emit(0, 1, 2)
    page.wrap_switch.set_checked(False)
    page.jump.click()
    settle(lambda: not page._end_pending)  # pyright: ignore[reportPrivateUsage]
    assert page.follow_switch.is_checked()
    page.scroll_home()
    assert not page.follow_switch.is_checked()
    page.follow_switch.set_checked(True)
    page.follow_switch.set_checked(False)
    page.wrap_switch.set_checked(True)
    with page.source.tail.path.open("a", encoding="utf-8") as handle:
        handle.write(line(9, "INFO", "chatimport.worker", "tail", minute=5))
    page.source._poll()  # pyright: ignore[reportPrivateUsage]
    page._fit_rows()  # pyright: ignore[reportPrivateUsage]
    bar.setValue(bar.maximum())
    page.table.viewport().grab()
    page.hide()


def test_older_batches(gui: GuiContext, settle: Settle, log_file: Path, toasts: Toasts) -> None:
    older = "".join(line(i, "INFO", "chatimport.old", f"old {i}") for i in range(10, 16))
    log_file.with_name(LOG_FILE + ".1").write_text(older, encoding="utf-8")
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    assert page.older_button.isEnabled()
    page.follow_switch.set_checked(False)
    page.older_button.click()
    assert page.source.busy
    settle(lambda: not page.source.busy)
    assert page.model.rowCount() == 11
    assert "success" in toasts.tones()
    page.older_button.click()
    settle(lambda: not page.source.busy)
    page.source.load_older()
    page.hide()


def test_older_when_full_and_exhausted(
    gui: GuiContext, settle: Settle, log_file: Path, toasts: Toasts
) -> None:
    older = "".join(line(i, "INFO", "chatimport.old", f"old {i}") for i in range(10, 16))
    log_file.with_name(LOG_FILE + ".1").write_text(older, encoding="utf-8")
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    page.model._limit = 7  # pyright: ignore[reportPrivateUsage]
    page.older_button.click()
    settle(lambda: not page.source.busy)
    assert "warning" in toasts.tones()
    page._on_older([], True)  # pyright: ignore[reportPrivateUsage]
    assert toasts.tones()[-1] == "info"
    page._on_older([], False)  # pyright: ignore[reportPrivateUsage]
    page.hide()


def test_load_failure(
    gui: GuiContext, settle: Settle, toasts: Toasts, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = LogPage(gui)

    def boom(_target: int) -> list[object]:
        raise RuntimeError("x")

    monkeypatch.setattr(page.source.tail, "load_tail", boom)
    page.show()
    settle(lambda: bool(toasts.items))
    assert toasts.tones() == ["danger"]
    monkeypatch.setattr(page.source.tail, "load_older", boom)
    page.source.load_older()
    settle(lambda: len(toasts.items) == 2)
    page.hide()


def test_language_switch(gui: GuiContext, settle: Settle, log_file: Path) -> None:
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    gui.language.set_language("ru")
    assert page.follow_switch._label.text()  # pyright: ignore[reportPrivateUsage]
    gui.language.set_language("en")
    page.table.selectRow(0)
    assert page.table.currentIndex().data(Qt.ItemDataRole.DisplayRole)
    page.hide()


def test_anchor_and_follow_edges(gui: GuiContext, settle: Settle, log_file: Path) -> None:
    log_file.write_text(sample(), encoding="utf-8")
    page = open_page(gui, settle)
    page.follow_switch.set_checked(False)
    page.search.query_changed.emit("zzz")
    assert page._top_anchor() is None  # pyright: ignore[reportPrivateUsage]
    page._restore_anchor(None)  # pyright: ignore[reportPrivateUsage]
    page.search.query_changed.emit("critical fatal")
    hidden = QPersistentModelIndex(page.model.index(0, 0))
    page.search.query_changed.emit("fatal")
    page._restore_anchor(hidden)  # pyright: ignore[reportPrivateUsage]
    page._do_end()  # pyright: ignore[reportPrivateUsage]
    page.follow_switch.set_checked(True)
    bar = page.table.verticalScrollBar()
    page._on_scrolled(bar.maximum())  # pyright: ignore[reportPrivateUsage]
    assert page.follow_switch.is_checked()
    page.hide()


def test_wrap_with_no_rows(gui: GuiContext, settle: Settle) -> None:
    page = open_page(gui, settle)
    page.wrap_switch.set_checked(True)
    page._fit_rows()  # pyright: ignore[reportPrivateUsage]
    page.hide()
