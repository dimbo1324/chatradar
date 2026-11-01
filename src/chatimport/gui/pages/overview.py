"""The Overview page: what the archive holds, what runs now, and what changed lately."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from chatimport.config import GIB
from chatimport.gui.format import (
    Freshness,
    classify,
    count_phrase,
    format_ago,
    format_bytes,
    format_count,
    humanize_age,
)
from chatimport.gui.i18n import plural, tr
from chatimport.gui.locales import overview as _overview_strings
from chatimport.gui.models.feed import EventFeed
from chatimport.gui.models.presentation import age_seconds, status_kind
from chatimport.gui.models.snapshot import SnapshotView, parse_snapshot
from chatimport.gui.models.ticker import shared_ticker
from chatimport.gui.pages.overview_feed import FeedList
from chatimport.gui.pages.support import clear_layout
from chatimport.gui.strings import current_language
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.progress import BusyStripe
from chatimport.gui.widgets.stat_card import StatCard
from chatimport.paths import cloud_sync_warning
from chatimport.runtime import BackfillState

if TYPE_CHECKING:
    from datetime import datetime

    from chatimport.gui.context import GuiContext
    from chatimport.gui.models.snapshot import ChatRow

_ = _overview_strings
COLUMNS: Final = 3
LOW_DISK_WARNING_FACTOR: Final = 1.5
MAX_ERROR_CALLOUTS: Final = 3
ERROR_CHARS: Final = 200

_FRESHNESS_TONE: Final[dict[Freshness, Tone]] = {
    Freshness.FRESH: "live",
    Freshness.RECENT: "neutral",
    Freshness.STALE: "warning",
    Freshness.DORMANT: "muted",
    Freshness.UNKNOWN: "neutral",
}
_SERVICE_TONE: Final[dict[str, Tone]] = {
    "running": "live",
    "starting": "info",
    "stopping": "warning",
    "stopped": "muted",
}


class BackfillCard(StatCard):
    """A stat card with a busy stripe along its bottom edge while history is downloading."""

    def __init__(self, gui: GuiContext, label: str) -> None:
        super().__init__(gui.kit, label, icon_name="download")
        self.stripe = BusyStripe(gui.kit)
        self._column.addWidget(self.stripe)

    def set_busy(self, busy: bool) -> None:
        self.stripe.set_active(busy)


class OverviewPage(QWidget):
    title_key = "nav.overview"
    subtitle_key = "overview.subtitle"

    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        kit = gui.kit
        self._ticker = shared_ticker()
        self._view = SnapshotView()
        self._feed = EventFeed()
        self._seen = False
        self._baseline_records = 0
        self._running_since: datetime | None = None
        self._callout_signature: tuple[object, ...] = ()
        self._cloud_warned = cloud_sync_warning(gui.service.root) is not None

        self.backfill_card = BackfillCard(gui, "")
        self.cards: dict[str, StatCard] = {
            "chats": StatCard(kit, "", icon_name="chats"),
            "messages": StatCard(kit, "", icon_name="hash"),
            "disk": StatCard(kit, "", icon_name="disk"),
            "backfill": self.backfill_card,
            "quiet": StatCard(kit, "", icon_name="clock"),
            "service": StatCard(kit, "", icon_name="activity"),
        }
        self._grid = QGridLayout()
        for position, card in enumerate(self.cards.values()):
            self._grid.addWidget(card, position // COLUMNS, position % COLUMNS)
        for column in range(COLUMNS):
            self._grid.setColumnStretch(column, 1)
        self._callouts = QVBoxLayout()
        self.feed_list = FeedList(kit)

        content = QWidget()
        content.setObjectName("OverviewContent")
        self._content = content
        self._stack = QVBoxLayout(content)
        self._stack.addLayout(self._callouts)
        self._stack.addLayout(self._grid)
        self._stack.addWidget(self.feed_list)
        self._stack.addStretch(1)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        wrap.addWidget(content, 100)
        wrap.addStretch(1)
        host = QWidget()
        host.setLayout(wrap)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(host)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        self._ticker.second.connect(self._on_second)
        gui.bridge.snapshot.connect(self.set_snapshot)
        bind_kit(kit, zoom=self._restyle, language=self._refresh_all)
        self._restyle()
        last = gui.bridge.last_snapshot
        if last is not None:
            self.set_snapshot(last)
        else:
            self._refresh_all()

    def set_snapshot(self, raw: dict[str, Any]) -> None:
        view = parse_snapshot(raw)
        now = self._ticker.now()
        if not self._seen:
            self._seen = True
            self._baseline_records = sum(row.records for row in view.chats)
        self._view = view
        if view.service == "running":
            self._running_since = self._running_since or now
        else:
            self._running_since = None
        self._feed.observe(view, now)
        self._refresh_all()

    def _on_second(self) -> None:
        now = self._ticker.now()
        self._refresh_cards(now)
        self.feed_list.refresh_time(now)

    def _refresh_all(self) -> None:
        now = self._ticker.now()
        self._refresh_cards(now)
        self._refresh_callouts()
        self.feed_list.set_events(self._feed.events, now)

    def _restyle(self) -> None:
        px = self.gui.kit.px
        self._content.setMaximumWidth(px(LAYOUT["content_max"]))
        pad = px(SPACE[8])
        self._stack.setContentsMargins(pad, px(SPACE[7]), pad, px(SPACE[8]))
        self._stack.setSpacing(px(SPACE[6]))
        self._grid.setSpacing(px(SPACE[5]))
        self._callouts.setSpacing(px(SPACE[4]))

    def _title_of(self, chat_id: int) -> str:
        row = self._view.chat(chat_id)
        return row.title if row is not None else str(chat_id)

    def _quietest(self, now: datetime) -> tuple[ChatRow, float] | None:
        best: tuple[ChatRow, float] | None = None
        for row in self._view.chats:
            age = age_seconds(row, now)
            if age is not None and (best is None or age > best[1]):
                best = (row, age)
        return best

    def _refresh_cards(self, now: datetime) -> None:
        view = self._view
        language = current_language()
        rows = view.chats
        live = sum(1 for row in rows if status_kind(row) == "live")
        self.cards["chats"].set_label(tr("overview.stat.chats"))
        self.cards["chats"].set_value(format_count(len(rows), language))
        self.cards["chats"].set_hint(tr("overview.stat.chats_hint", live=live))
        self.cards["chats"].set_tone("live" if live else "neutral")

        total = sum(row.records for row in rows)
        fresh = max(total - self._baseline_records, 0)
        self.cards["messages"].set_label(tr("overview.stat.messages"))
        self.cards["messages"].set_value(format_count(total, language))
        self.cards["messages"].set_hint(
            count_phrase(fresh, "overview.stat.messages_new", language)
            if fresh
            else tr("overview.stat.messages_none")
        )

        self._refresh_disk()
        self._refresh_backfill()
        self._refresh_quiet(now)
        self._refresh_service(now)

    def _refresh_disk(self) -> None:
        view = self._view
        card = self.cards["disk"]
        language = current_language()
        card.set_label(tr("overview.stat.disk"))
        if view.free_gb is None:
            card.set_value(tr("overview.stat.disk_unknown"))
            card.set_hint("")
            card.set_tone("neutral")
            return
        card.set_value(format_bytes(view.free_gb * GIB, language))
        card.set_hint(tr("overview.stat.disk_hint", size=format_bytes(view.total_bytes, language)))
        card.set_tone(self._disk_tone())

    def _disk_tone(self) -> Tone:
        free, low = self._view.free_gb, self._view.low_watermark_gb
        if free is None or not low:
            return "neutral"
        if free < low:
            return "danger"
        return "warning" if free < low * LOW_DISK_WARNING_FACTOR else "neutral"

    def _refresh_backfill(self) -> None:
        view = self._view
        card = self.backfill_card
        active = list(view.backfill.active)
        waiting = len(view.backfill.waiting)
        card.set_label(tr("overview.stat.backfill"))
        if active:
            title = self._title_of(active[0])
            card.set_value(tr("overview.backfill.running"))
            card.set_hint(
                tr("overview.backfill.hint_waiting", title=title, n=waiting)
                if waiting
                else tr("overview.backfill.hint_running", title=title)
            )
            card.set_tone("live")
            card.set_busy(True)
            return
        card.set_busy(False)
        if waiting:
            card.set_value(plural(waiting, "overview.backfill.waiting"))
            card.set_hint("")
            card.set_tone("neutral")
        elif view.chats and all(
            row.backfill.state in (BackfillState.DONE, BackfillState.NO_ACCESS)
            for row in view.chats
        ):
            card.set_value(tr("overview.backfill.done"))
            card.set_hint(tr("overview.backfill.hint_done"))
            card.set_tone("success")
        else:
            card.set_value(tr("overview.backfill.idle"))
            card.set_hint(tr("overview.backfill.hint_idle"))
            card.set_tone("neutral")

    def _refresh_quiet(self, now: datetime) -> None:
        card = self.cards["quiet"]
        language = current_language()
        card.set_label(tr("overview.stat.quiet"))
        best = self._quietest(now)
        if best is None:
            card.set_value(tr("overview.quiet.none"))
            card.set_hint(tr("overview.quiet.hint_none"))
            card.set_tone("neutral")
            return
        row, age = best
        thresholds = self.gui.settings.settings.thresholds_for(row.chat_id)
        card.set_value(humanize_age(age, language))
        card.set_hint(row.title)
        card.set_tone(_FRESHNESS_TONE[classify(age, thresholds)])

    def _refresh_service(self, now: datetime) -> None:
        view = self._view
        card = self.cards["service"]
        language = current_language()
        state = view.service if view.service in _SERVICE_TONE else "stopped"
        card.set_label(tr("overview.stat.service"))
        card.set_value(tr(f"overview.service.{state}"))
        card.set_tone(_SERVICE_TONE[state])
        updated = (
            format_ago(max((now - view.updated_at).total_seconds(), 0.0), language)
            if view.updated_at
            else tr("time.unknown")
        )
        if self._running_since is not None:
            up = humanize_age((now - self._running_since).total_seconds(), language)
            card.set_hint(tr("overview.service.hint", up=up, updated=updated))
        else:
            card.set_hint(tr("overview.service.hint_stopped", updated=updated))

    def _refresh_callouts(self) -> None:
        wanted = self._callout_specs()
        signature = (current_language(), *wanted)
        if signature == self._callout_signature:
            return
        self._callout_signature = signature
        clear_layout(self._callouts)
        for tone, title, body in wanted:
            self._callouts.addWidget(Callout(self.gui.kit, tone, body, title=title))

    def _callout_specs(self) -> list[tuple[Tone, str, str]]:
        view = self._view
        language = current_language()
        specs: list[tuple[Tone, str, str]] = []
        plain = [error for error in view.errors if not error.is_resolve]
        for error in plain[:MAX_ERROR_CALLOUTS]:
            body = f"{error.source}: {error.message}"[:ERROR_CHARS]
            specs.append(("danger", tr("overview.callout.errors"), body))
        missing = len(view.errors) - len(plain)
        if missing:
            specs.append(
                (
                    "warning",
                    plural(missing, "overview.callout.join.title"),
                    tr("overview.callout.join.text"),
                )
            )
        if self._cloud_warned:
            specs.append(
                (
                    "warning",
                    tr("overview.callout.cloud.title"),
                    tr("overview.callout.cloud.text"),
                )
            )
        if view.free_gb is not None and view.low_watermark_gb and self._disk_tone() != "neutral":
            specs.append(
                (
                    self._disk_tone(),
                    tr("overview.callout.disk.title"),
                    tr(
                        "overview.callout.disk.text",
                        free=format_bytes(view.free_gb * GIB, language),
                        limit=format_bytes(view.low_watermark_gb * GIB, language),
                    ),
                )
            )
        return specs
