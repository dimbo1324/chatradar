from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtWidgets import QApplication

from chatimport.gui.models.ticker import shared_ticker
from chatimport.gui.pages import overview as overview_module
from chatimport.gui.pages.overview import BackfillCard, OverviewPage
from chatimport.gui.widgets.callout import Callout

from .conftest import NOW, chat, everything, snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.gui.context import GuiContext
    from tests.unit.gui.conftest import FakeBridge


def make(gui: GuiContext) -> OverviewPage:
    page = OverviewPage(gui)
    page.resize(900, 700)
    return page


def callouts(page: OverviewPage) -> list[Callout]:
    return page.findChildren(Callout)


def test_empty_page_renders_neutral_cards(gui: GuiContext) -> None:
    page = make(gui)
    assert set(page.cards) == {"chats", "messages", "disk", "backfill", "quiet", "service"}
    assert callouts(page) == []
    assert page.cards["disk"].isVisibleTo(page)
    assert page.grab().width() > 0


def test_last_snapshot_is_applied_on_construction(gui: GuiContext, bridge: FakeBridge) -> None:
    bridge.last_snapshot = snapshot([chat(1, "Alpha")])
    page = make(gui)
    assert page._view.chat(1) is not None
    assert page._running_since == NOW


def test_snapshot_signal_updates_and_baseline_counts_new_messages(
    gui: GuiContext, bridge: FakeBridge
) -> None:
    page = make(gui)
    bridge.snapshot.emit(snapshot([chat(1, "Alpha", records=10)]))
    assert page._baseline_records == 10
    bridge.snapshot.emit(snapshot([chat(1, "Alpha", records=15)]))
    assert page._baseline_records == 10
    assert page._running_since == NOW
    bridge.snapshot.emit(snapshot([chat(1, "Alpha", records=15)], service="stopped"))
    assert page._running_since is None


def test_messages_hint_without_new_ones(gui: GuiContext) -> None:
    page = make(gui)
    page.set_snapshot(snapshot([chat(1, "Alpha", records=10)]))
    page.set_snapshot(snapshot([chat(1, "Alpha", records=10)]))
    assert page.cards["messages"] is not None


def test_service_states_and_unknown_state(gui: GuiContext) -> None:
    page = make(gui)
    for state in ("running", "starting", "stopping", "stopped", "weird"):
        page.set_snapshot(snapshot([chat(1)], service=state))
    raw = snapshot([chat(1)])
    del raw["updated_at"]
    page.set_snapshot(raw)
    page.set_snapshot({})
    assert page._view.service == "stopped"


@pytest.mark.parametrize(
    ("free", "low", "expected"),
    [
        (None, 10.0, "neutral"),
        (200.0, None, "neutral"),
        (5.0, 10.0, "danger"),
        (12.0, 10.0, "warning"),
        (200.0, 10.0, "neutral"),
    ],
)
def test_disk_tones(gui: GuiContext, free: float | None, low: float | None, expected: str) -> None:
    page = make(gui)
    page.set_snapshot(snapshot([chat(1)], free_gb=free, low_gb=low))
    assert page._disk_tone() == expected
    has_disk_callout = any(spec[1] for spec in page._callout_specs() if spec[0] == expected)
    assert has_disk_callout == (expected != "neutral")


def test_backfill_card_variants(gui: GuiContext) -> None:
    page = make(gui)
    page.set_snapshot(snapshot([chat(1, "A", state="running"), chat(2, "B")], active=[1]))
    page.set_snapshot(
        snapshot([chat(1, "A", state="running"), chat(2, "B")], active=[1], waiting=[2])
    )
    page.set_snapshot(snapshot([chat(1, "A", state="waiting")], waiting=[1]))
    page.set_snapshot(snapshot([chat(1, "A", state="done"), chat(2, "B", state="no_access")]))
    page.set_snapshot(snapshot([chat(1, "A", state="idle")]))
    page.set_snapshot(snapshot([]))
    page.set_snapshot(snapshot([chat(1, "A", state="running")], active=[99]))


def test_quiet_card_with_and_without_age(gui: GuiContext) -> None:
    page = make(gui)
    page.set_snapshot(snapshot([chat(1, "A", age=None)]))
    page.set_snapshot(
        snapshot([chat(1, "A", age=60), chat(2, "B", age=900_000), chat(3, "C", age=5)])
    )
    assert page._quietest(NOW) is not None
    assert page._quietest(NOW)[0].chat_id == 2  # type: ignore[index]


def test_everything_snapshot_builds_all_callouts(
    gui: GuiContext, monkeypatch: pytest.MonkeyPatch
) -> None:

    def warn(_root: Path) -> str:
        return "warn"

    monkeypatch.setattr(overview_module, "cloud_sync_warning", warn)
    page = make(gui)
    raw = everything()
    raw["errors"] = [{"source": f"worker:{i}", "message": "x" * 300} for i in range(5)] + [
        {"source": "resolve:@gone", "message": "unresolved"}
    ]
    raw["disk"]["free_gb"] = 1.0
    page.set_snapshot(raw)
    specs = page._callout_specs()
    assert len(callouts(page)) == len(specs) == 3 + 1 + 1 + 1
    assert all(len(body) <= overview_module.ERROR_CHARS for _, _, body in specs[:3])


def test_callouts_are_not_rebuilt_when_unchanged(gui: GuiContext) -> None:
    page = make(gui)
    raw = snapshot([chat(1)], errors=[{"source": "worker:1", "message": "bad"}])
    page.set_snapshot(raw)
    first = callouts(page)
    page.set_snapshot(raw)
    assert callouts(page) == first
    page.set_snapshot(snapshot([chat(1)]))
    assert callouts(page) == []


def test_feed_receives_events_and_ticks(gui: GuiContext, bridge: FakeBridge) -> None:
    page = make(gui)
    bridge.snapshot.emit(snapshot([chat(1, "Alpha", phase="starting")]))
    bridge.snapshot.emit(snapshot([chat(1, "Alpha", phase="live"), chat(2, "Bravo")]))
    assert len(page._feed.events) == 2
    shared_ticker().second.emit()
    QApplication.processEvents()
    assert len(page.feed_list._widgets) == 2


def test_language_and_zoom_changes_refresh(gui: GuiContext) -> None:
    page = make(gui)
    page.set_snapshot(everything())
    gui.language.set_language("ru")
    gui.zoom.zoom_in()
    gui.language.set_language("en")
    assert page.cards["service"] is not None


def test_backfill_card_busy_toggle(gui: GuiContext) -> None:
    card = BackfillCard(gui, "x")
    card.set_busy(True)
    card.set_busy(False)
