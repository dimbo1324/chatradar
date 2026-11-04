# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QObject, QRect
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

import chatimport.gui.main_window as main_window
from chatimport.gui.models.presentation import ChipSpec
from chatimport.gui.notifier import QtNotifier
from chatimport.gui.pages import PAGE_KEYS, build_pages
from chatimport.gui.pages.paint import (
    chip_height,
    chip_width,
    draw_bar,
    draw_chip,
    draw_dot,
    token_font,
)
from chatimport.gui.pages.placeholder import PlaceholderPage
from chatimport.gui.pages.support import (
    MainThreadRunner,
    clear_layout,
    find_toasts,
    notify,
)
from chatimport.gui.shell_state import (
    DownloadSummary,
    chats_of,
    download_summary,
    service_state,
)
from chatimport.gui.shell_widgets import DownloadIndicator, ServiceChip
from chatimport.gui.widgets.toast import ToastHost
from chatimport.runtime import Level

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.kit import UiKit


_ = main_window


def test_chats_of_filters_non_dicts() -> None:
    assert chats_of(None) == []
    assert chats_of({"chats": "x"}) == []
    assert chats_of({"chats": [{"a": 1}, 3]}) == [{"a": 1}]


def test_service_state() -> None:
    assert service_state(None, True) == "failed"
    assert service_state(None, False) == "starting"
    assert service_state({"service": "weird"}, False) == "stopped"
    assert service_state({}, False) == "stopped"
    assert service_state({"service": "running"}, False) == "running"
    paused = {"service": "running", "chats": [{"paused": True}, {"paused": True}]}
    assert service_state(paused, False) == "paused"
    mixed = {"service": "running", "chats": [{"paused": True}, {}]}
    assert service_state(mixed, False) == "running"
    assert service_state({"service": "needs_setup"}, False) == "needs_setup"


def test_download_summary_active_and_queued() -> None:
    chats = [{"chat_id": 1, "title": "Alpha"}, {"chat_id": 2}]
    active = {"chats": chats, "backfill": {"active": [1, "x", 2], "waiting": [3, 4]}}
    assert download_summary(active) == DownloadSummary("active", "Alpha", 1, 2)
    untitled = {"chats": chats, "backfill": {"active": [2]}}
    assert download_summary(untitled).chat == "2"
    unknown = {"chats": chats, "backfill": {"active": [9]}}
    assert download_summary(unknown).chat == "9"
    queued = {"chats": chats, "backfill": {"waiting": [1]}}
    assert download_summary(queued) == DownloadSummary("queued", waiting=1)
    assert download_summary({"backfill": {"active": "no"}}).kind == "empty"
    assert download_summary({"backfill": []}).kind == "empty"


@pytest.mark.parametrize(
    ("state", "kind"),
    [("retrying", "retrying"), ("disk_stopped", "disk"), ("paused", "paused")],
)
def test_download_summary_idle_kinds(state: str, kind: str) -> None:
    chats = [{"chat_id": 1, "backfill": {"state": state}}, {"chat_id": 2, "backfill": 5}]
    assert download_summary({"chats": chats}).kind == kind


def test_download_summary_done_and_empty() -> None:
    done = {"chats": [{"chat_id": 1, "backfill": {"state": "done"}}]}
    assert download_summary(done).kind == "done"
    assert download_summary(None).kind == "empty"


def test_notifier_delivers_and_ignores_bad_level(
    qapp: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    notifier = QtNotifier()
    got: list[tuple[object, str, str]] = []
    notifier.delivered.connect(lambda level, title, msg: got.append((level, title, msg)))
    with caplog.at_level(logging.INFO, logger="chatimport.notify"):
        notifier.notify(Level.WARNING, "T", "M")
    qapp.processEvents()
    assert got == [(Level.WARNING, "T", "M")]
    assert "T: M" in caplog.text
    notifier._on_incoming("not a level", "T", "M")
    assert len(got) == 1


def test_service_chip(kit: UiKit) -> None:
    chip = ServiceChip(kit)
    assert chip.state == "starting"
    chip.update_from({"service": "running"}, False)
    assert chip.state == "running"
    chip.update_from(None, True)
    assert chip.state == "failed"
    kit.language.set_language("ru")
    assert chip.toolTip()


def test_download_indicator(kit: UiKit) -> None:
    indicator = DownloadIndicator(kit)
    assert indicator.summary.kind == "empty"
    indicator.update_from(None)
    assert indicator.text
    indicator.set_summary(DownloadSummary("active", "Alpha", 2, 3))
    assert "Alpha" in indicator.text
    assert indicator._icon.isHidden()
    indicator.set_summary(DownloadSummary("active", "Alpha"))
    assert "Alpha" in indicator.text
    indicator.set_summary(DownloadSummary("queued", waiting=2))
    assert indicator.text
    for kind in ("retrying", "disk", "paused", "done", "empty"):
        indicator.set_summary(DownloadSummary(kind))  # type: ignore[arg-type]
    kit.language.set_language("ru")
    kit.zoom.zoom_in()


def test_paint_helpers(kit: UiKit, qapp: QApplication) -> None:
    font = token_font(QFont(), kit, "xs", "medium")
    assert font.pixelSize() > 0
    spec = ChipSpec("Live", "live", "check")
    assert chip_height(kit) > 0
    assert chip_width(kit, spec, font) > 0
    image = QImage(300, 60, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    width = draw_chip(painter, kit, spec, 2, 2, QFont())
    assert width > 0
    rect = QRect(0, 30, 200, 6)
    draw_bar(painter, kit, rect, None, "#336699", 0.5)
    draw_bar(painter, kit, rect, 0.5, "#336699", 0.5)
    assert draw_dot(painter, kit, "#336699", 4, 40) == kit.px(7)
    painter.end()


def test_support_helpers(kit: UiKit, qapp: QApplication) -> None:
    window = QWidget()
    child = QWidget(window)
    assert find_toasts(child) is None
    notify(child, "info", "nobody listens")
    host = ToastHost(kit, window)
    assert find_toasts(child) is host
    notify(child, "info", "hello")
    assert host.count == 1
    layout = QVBoxLayout(window)
    layout.addWidget(QWidget())
    layout.addWidget(QWidget())
    layout.addStretch(1)
    clear_layout(layout)
    assert layout.count() == 0
    window.close()


def test_main_thread_runner(qapp: QApplication) -> None:
    runner = QObject()
    main = MainThreadRunner(runner)
    done: list[int] = []
    future = main.submit(lambda: 41 + 1, lambda finished: done.append(finished.result()))
    assert future.result(timeout=5) == 42
    for _ in range(100):
        qapp.processEvents()
        if done:
            break
    assert done == [42]
    watched: Future[int] = Future()
    seen: list[int] = []
    main.watch(watched, lambda finished: seen.append(finished.result()))
    watched.set_result(7)
    qapp.processEvents()
    assert seen == [7]
    main._invoke("not callable")
    main.shutdown()


@pytest.mark.parametrize("key", ["log", "data", "settings", "other"])
def test_placeholder_page(gui: GuiContext, key: str) -> None:
    page = PlaceholderPage(gui, key)
    assert page.title_key == f"nav.{key}"
    gui.language.set_language("ru")


def test_build_pages(gui: GuiContext, qapp: QApplication) -> None:
    pages = build_pages(gui)
    assert tuple(pages) == PAGE_KEYS
    for page in pages.values():
        page.close()
