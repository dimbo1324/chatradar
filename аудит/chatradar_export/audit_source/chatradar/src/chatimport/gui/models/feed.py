"""The Overview's event feed: what changed between two consecutive snapshots.

Pure and Qt-free. The first snapshot only sets the baseline, so opening the window never
replays history as news. Events carry a translation key and a chat title, never Telegram text.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chatimport.gui.models.snapshot import (
    PHASE_LIVE,
    PHASE_NO_ACCESS,
    PHASE_PAUSED,
    ChatRow,
    SnapshotView,
)
from chatimport.runtime import BackfillState

if TYPE_CHECKING:
    from datetime import datetime

    from chatimport.gui.widgets.base import Tone

MAX_EVENTS: Final = 50

_BACKFILL_EVENTS: Final[dict[BackfillState, tuple[str, Tone, str]]] = {
    BackfillState.RUNNING: ("feed.backfill_running", "live", "download"),
    BackfillState.DONE: ("feed.backfill_done", "success", "check-circle"),
    BackfillState.PAUSED: ("feed.backfill_paused", "muted", "pause"),
    BackfillState.DISK_STOPPED: ("feed.backfill_disk", "warning", "disk"),
    BackfillState.RETRYING: ("feed.backfill_retrying", "warning", "refresh"),
    BackfillState.NO_ACCESS: ("feed.no_access", "danger", "ban"),
}
_PHASE_EVENTS: Final[dict[str, tuple[str, Tone, str]]] = {
    PHASE_LIVE: ("feed.live", "live", "radio"),
    PHASE_PAUSED: ("feed.paused", "muted", "pause"),
    PHASE_NO_ACCESS: ("feed.no_access", "danger", "ban"),
}


@dataclass(frozen=True, slots=True)
class FeedEvent:
    key: str
    tone: Tone
    icon: str
    at: datetime
    title: str = ""


class EventFeed:
    def __init__(self, limit: int = MAX_EVENTS) -> None:
        self._events: deque[FeedEvent] = deque(maxlen=limit)
        self._previous: SnapshotView | None = None

    @property
    def events(self) -> tuple[FeedEvent, ...]:
        """Newest first."""
        return tuple(reversed(self._events))

    def observe(self, view: SnapshotView, now: datetime) -> list[FeedEvent]:
        previous, self._previous = self._previous, view
        if previous is None:
            return []
        found: list[FeedEvent] = []
        old_rows = {row.chat_id: row for row in previous.chats}
        new_ids: set[int] = set()
        for row in view.chats:
            new_ids.add(row.chat_id)
            before = old_rows.get(row.chat_id)
            if before is None:
                found.append(FeedEvent("feed.chat_added", "info", "plus", now, row.title))
            else:
                found.extend(self._chat_events(before, row, now))
        found.extend(
            FeedEvent("feed.chat_removed", "muted", "minus", now, row.title)
            for row in previous.chats
            if row.chat_id not in new_ids
        )
        found.extend(self._error_events(previous, view, now))
        self._events.extend(found)
        return found

    @staticmethod
    def _chat_events(before: ChatRow, after: ChatRow, now: datetime) -> list[FeedEvent]:
        found: list[FeedEvent] = []
        if after.phase != before.phase and after.phase in _PHASE_EVENTS:
            key, tone, icon = _PHASE_EVENTS[after.phase]
            found.append(FeedEvent(key, tone, icon, now, after.title))
        state = after.backfill.state
        if state is not before.backfill.state and state in _BACKFILL_EVENTS:
            skip_duplicate = state is BackfillState.NO_ACCESS and found
            if not skip_duplicate:
                key, tone, icon = _BACKFILL_EVENTS[state]
                found.append(FeedEvent(key, tone, icon, now, after.title))
        return found

    @staticmethod
    def _error_events(before: SnapshotView, after: SnapshotView, now: datetime) -> list[FeedEvent]:
        old = {error.source for error in before.errors}
        new = {error.source for error in after.errors}
        found = [
            FeedEvent(
                "feed.error_resolve" if source.startswith("resolve:") else "feed.error",
                "danger",
                "alert",
                now,
            )
            for source in sorted(new - old)
        ]
        if old - new:
            found.append(FeedEvent("feed.error_cleared", "success", "check", now))
        return found
