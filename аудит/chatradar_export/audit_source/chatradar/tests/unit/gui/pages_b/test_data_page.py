from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QAbstractItemModel, QRect
from PySide6.QtGui import QImage, QPainter, QStandardItemModel
from PySide6.QtWidgets import QStyleOptionViewItem, QTableView

from chatimport.gui.models.data_models import IssueColumn, IssueRow, IssuesModel, UsageColumn
from chatimport.gui.pages import data as data_module
from chatimport.gui.pages.data import DataPage
from chatimport.gui.pages.data_common import (
    ChatSelector,
    FieldRow,
    SeverityDelegate,
    ShareBarDelegate,
    breakable,
    fit_table,
    prepare_table,
)
from chatimport.gui.pages.data_storage import free_disk_tone
from chatimport.usage import ArchiveUsage, archive_usage
from tests.unit.gui.pages_b.archive import ALPHA_ID, BETA_ID, build_archive

if TYPE_CHECKING:
    from collections.abc import Callable

    from chatimport.gui.context import GuiContext
    from tests.unit.gui.pages_b.conftest import Opened, Toasts


@pytest.fixture
def page(gui: GuiContext, qapp: object) -> DataPage:
    build_archive(gui.current.root)
    return DataPage(gui)


def test_free_disk_tone() -> None:
    assert free_disk_tone(None, 10) == "neutral"
    assert free_disk_tone(5, 0) == "neutral"
    assert free_disk_tone(5, 10) == "danger"
    assert free_disk_tone(12, 10) == "warning"
    assert free_disk_tone(100, 10) == "success"


def test_page_computes_usage_on_first_show(
    page: DataPage, settle: Callable[[Callable[[], bool]], None]
) -> None:
    page.show()
    settle(lambda: page.env.usage is not None)
    assert page.storage.model.rowCount() == 2
    assert not page.storage.empty.isVisibleTo(page)
    assert page.env.chats() == [(ALPHA_ID, "Alpha"), (BETA_ID, "Beta")]
    page.hide()
    page.show()
    assert page.env.usage is not None


def test_calculate_again_while_running_repeats_once(
    page: DataPage, settle: Callable[[Callable[[], bool]], None]
) -> None:
    page.calculate()
    page.calculate()
    page.calculate()
    settle(lambda: not page._calculating and not page._again and page.env.usage is not None)  # pyright: ignore[reportPrivateUsage]


def test_calculate_failure_toasts(
    page: DataPage,
    toasts: Toasts,
    settle: Callable[[Callable[[], bool]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(root: Path) -> ArchiveUsage:
        raise OSError("gone")

    monkeypatch.setattr(data_module, "archive_usage", boom)
    page.calculate()
    settle(lambda: bool(toasts.items))
    assert toasts.tones() == ["danger"]
    assert page.env.usage is None


def test_storage_card_empty_and_unknown_free(page: DataPage) -> None:
    storage = page.storage
    storage.set_busy(True)
    assert not storage.calculate.isEnabled()
    storage.retranslate()
    storage.set_busy(False)
    assert storage.calculate.isEnabled()
    page.env.usage = None
    storage._render()  # pyright: ignore[reportPrivateUsage]
    assert storage.empty.isHidden() is False
    empty = ArchiveUsage((), 0, 0, 0, None)
    page.env.set_usage(empty)
    page.show()
    assert storage.empty.isVisibleTo(page)
    assert not storage.table.isVisibleTo(page)


def test_storage_card_known_free(page: DataPage, tmp_path: Path) -> None:
    usage = archive_usage(page.env.root)
    page.env.set_usage(usage)
    assert page.storage.model.rowCount() == 2
    assert page.storage.cards["chats"] is not None
    assert page.storage.table.model().rowCount() == 2


def test_env_root_change_requests_usage(page: DataPage, tmp_path: Path) -> None:
    seen: list[str] = []
    page.env.request_usage.disconnect(page.calculate)
    page.env.request_usage.connect(lambda: seen.append("usage"))
    page.env.root_changed.connect(lambda: seen.append("root"))
    page.env.set_usage(archive_usage(page.env.root))
    page.env.set_root(tmp_path / "other")
    assert page.env.usage is None
    assert seen == ["root", "usage"]
    assert page.env.chats() == []


def test_env_open_folder(page: DataPage, opened: Opened, toasts: Toasts) -> None:
    page.env.open_folder(page.env.root)
    assert opened.urls == [str(page.env.root)]
    opened.ok = False
    page.env.open_folder(page.env.root)
    assert toasts.tones() == ["warning"]
    page.env.unavailable()
    assert toasts.tones() == ["warning", "warning"]


def test_env_chats_uses_id_when_title_missing(page: DataPage) -> None:
    from chatimport.usage import ChatUsage

    chats = (
        ChatUsage(7, None, Path("a"), 1, 0, 1, 1),
        ChatUsage(None, None, Path("b"), 1, 0, 1, None),
    )
    page.env.set_usage(ArchiveUsage(chats, 2, 0, 0, 1))
    assert page.env.chats() == [(7, "7")]
    assert page.storage.model.data(page.storage.model.index(0, 0)) is not None


def test_chat_selector(qapp: object) -> None:
    everyone = ChatSelector(allow_all=True)
    everyone.set_chats([(1, "One"), (2, "Two")])
    assert everyone.count() == 3
    assert everyone.chat_id() is None
    everyone.setCurrentIndex(2)
    everyone.set_chats([(2, "Two")])
    assert everyone.chat_id() == 2
    assert everyone.title() == "Two"
    single = ChatSelector(allow_all=False)
    single.rebuild()
    assert not single.isEnabled()
    assert single.chat_id() is None


def test_field_row_and_tables(gui: GuiContext, qapp: object) -> None:
    row = FieldRow(gui.kit, "a", ChatSelector(allow_all=False))
    row.set_caption("b")
    view = QTableView()
    prepare_table(view)
    fit_table(view, gui.kit, 0)
    small = view.height()
    fit_table(view, gui.kit, 100)
    assert view.height() > small


def test_breakable() -> None:
    assert breakable("a\\b/c") == "a\\​b/​c"


def paint(
    delegate: ShareBarDelegate | SeverityDelegate, model: QAbstractItemModel, row: int, column: int
) -> None:
    image = QImage(300, 40, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    view = QTableView()
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 300, 40)
    option.widget = view
    delegate.paint(painter, option, model.index(row, column))
    painter.end()


def test_share_bar_delegate(gui: GuiContext, page: DataPage) -> None:
    page.env.set_usage(archive_usage(page.env.root))
    delegate = ShareBarDelegate(gui.kit)
    model = page.storage.model
    paint(delegate, model, 0, UsageColumn.SHARE)
    paint(delegate, model, 1, UsageColumn.SHARE)
    paint(delegate, model, 0, UsageColumn.CHAT)
    paint(delegate, model, 99, UsageColumn.SHARE)
    foreign = QStandardItemModel(1, 5)
    paint(delegate, foreign, 0, UsageColumn.SHARE)


def test_severity_delegate(gui: GuiContext, qapp: object) -> None:
    model = IssuesModel()
    model.set_issues([IssueRow("error", "f", "m"), IssueRow("other", "f", "m")])
    delegate = SeverityDelegate(gui.kit)
    paint(delegate, model, 0, IssueColumn.SEVERITY)
    paint(delegate, model, 1, IssueColumn.SEVERITY)
    paint(delegate, model, 0, IssueColumn.MESSAGE)


def test_background_without_widget(gui: GuiContext, qapp: object) -> None:
    model = IssuesModel()
    model.set_issues([IssueRow("error", "f", "m")])
    delegate = SeverityDelegate(gui.kit)
    image = QImage(100, 40, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 100, 40)
    delegate.paint(painter, option, model.index(0, 0))
    painter.end()


def test_language_switch_retranslates(page: DataPage, gui: GuiContext) -> None:
    page.env.set_usage(archive_usage(page.env.root))
    gui.language.set_language("ru")
    assert page.storage._title.text() != "Storage"  # pyright: ignore[reportPrivateUsage]
    gui.language.set_language("en")


def test_storage_busy_future(page: DataPage) -> None:
    done: Future[ArchiveUsage] = Future()
    done.set_exception(OSError("x"))
    page._calculated(done)  # pyright: ignore[reportPrivateUsage]
    assert not page._calculating  # pyright: ignore[reportPrivateUsage]
