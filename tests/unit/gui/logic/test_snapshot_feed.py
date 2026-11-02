from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from chatimport.gui.models.feed import MAX_EVENTS, EventFeed
from chatimport.gui.models.snapshot import (
    PHASE_LIVE,
    PHASE_NO_ACCESS,
    PHASE_PAUSED,
    BackfillView,
    ChatRow,
    GlobalBackfill,
    ServiceError,
    SnapshotView,
    parse_chat,
    parse_dt,
    parse_snapshot,
)
from chatimport.runtime import BackfillState

NOW = datetime(2026, 10, 31, 20, 0, 0, tzinfo=UTC)


def chat(chat_id: int = 1, **changes: Any) -> ChatRow:
    return replace(ChatRow(chat_id, f"Chat {chat_id}", PHASE_LIVE), **changes)


def view(*chats: ChatRow, errors: tuple[ServiceError, ...] = ()) -> SnapshotView:
    return SnapshotView(chats=chats, errors=errors)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (5, None),
        ("not a date", None),
        ("2026-10-31T20:00:00Z", NOW),
        ("2026-10-31T23:00:00+03:00", NOW),
        ("2026-10-31T20:00:00", NOW),
        ("2026-10-31T19:00:00-01:00", NOW),
    ],
)
def test_parse_dt(value: object, expected: datetime | None) -> None:
    assert parse_dt(value) == expected
    if expected is not None:
        assert parse_dt(value).tzinfo is UTC  # type: ignore[union-attr]


def test_parse_chat_rejects_a_bad_id() -> None:
    assert parse_chat({}) is None
    assert parse_chat({"chat_id": "5"}) is None
    assert parse_chat({"chat_id": True}) is None


def test_parse_chat_defaults() -> None:
    row = parse_chat({"chat_id": 42})
    assert row == ChatRow(42, "42", "")
    assert row is not None
    assert row.backfill == BackfillView()


def test_parse_chat_full_and_tolerant() -> None:
    row = parse_chat(
        {
            "chat_id": 7,
            "title": "Example group",
            "phase": "live",
            "last_id": 99,
            "records": 1234,
            "paused": True,
            "backfill_done": True,
            "oldest_date": "2026-01-01T00:00:00Z",
            "newest_date": "2026-10-31T20:00:00Z",
            "last_contact_at": "garbage",
            "error": "",
            "backfill": {
                "state": "retrying",
                "progress": 0.5,
                "month": "2026-03",
                "retry_at": "2026-10-31T20:05:00Z",
                "detail": "flood wait",
            },
        }
    )
    assert row is not None
    assert (row.title, row.phase, row.last_id, row.records) == ("Example group", "live", 99, 1234)
    assert row.paused
    assert row.backfill_done
    assert row.oldest_date == datetime(2026, 1, 1, tzinfo=UTC)
    assert row.last_contact_at is None
    assert row.error is None
    assert row.backfill == BackfillView(
        BackfillState.RETRYING, 0.5, "2026-03", NOW + timedelta(minutes=5), "flood wait"
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"state": "nonsense", "progress": True},
        {"state": None, "progress": "x"},
        "not a mapping",
    ],
)
def test_parse_chat_survives_a_malformed_backfill(raw: Any) -> None:
    row = parse_chat({"chat_id": 1, "backfill": raw, "last_id": True, "records": "9"})
    assert row is not None
    assert row.backfill.state is BackfillState.IDLE
    assert row.backfill.progress is None
    assert (row.last_id, row.records) == (0, 0)


def test_chat_row_flags() -> None:
    assert chat().has_access
    assert not chat().is_paused
    assert not chat().has_problem
    assert not chat(phase=PHASE_NO_ACCESS).has_access
    assert not chat(backfill=BackfillView(BackfillState.NO_ACCESS)).has_access
    assert chat(paused=True).is_paused
    assert chat(phase=PHASE_PAUSED).is_paused
    assert chat(phase=PHASE_NO_ACCESS).has_problem
    assert chat(error="boom").has_problem
    assert chat(backfill=BackfillView(BackfillState.RETRYING)).has_problem


def test_service_error_resolve_flag() -> None:
    assert ServiceError("resolve:abc", "x").is_resolve
    assert not ServiceError("worker:1", "x").is_resolve


def test_parse_snapshot_empty() -> None:
    assert parse_snapshot(None) == SnapshotView()
    assert parse_snapshot({}) == SnapshotView()


def test_parse_snapshot_full() -> None:
    snapshot = parse_snapshot(
        {
            "service": "running",
            "updated_at": "2026-10-31T20:00:00Z",
            "disk": {"path": "D:/data", "free_gb": 12.5, "low_watermark_gb": 5},
            "total_bytes": 4096,
            "backfill": {"limit": 0, "active": [1, 2], "waiting": [3, "x", 4]},
            "chats": [{"chat_id": 1, "title": "A"}, {"chat_id": "bad"}, "junk", {"chat_id": 2}],
            "errors": [
                {"source": "resolve:x", "message": "no such chat"},
                {"source": 5},
                "junk",
            ],
        }
    )
    assert snapshot.service == "running"
    assert snapshot.updated_at == NOW
    assert (snapshot.disk_path, snapshot.free_gb, snapshot.low_watermark_gb) == (
        "D:/data",
        12.5,
        5.0,
    )
    assert snapshot.total_bytes == 4096
    assert snapshot.backfill == GlobalBackfill(limit=1, active=(1, 2), waiting=(3, 4))
    assert [row.chat_id for row in snapshot.chats] == [1, 2]
    assert snapshot.errors == (ServiceError("resolve:x", "no such chat"), ServiceError("", ""))
    assert snapshot.chat(2) is snapshot.chats[1]
    assert snapshot.chat(99) is None


def test_parse_snapshot_with_wrong_container_types() -> None:
    snapshot = parse_snapshot(
        {"disk": [], "backfill": 3, "chats": "x", "errors": {}, "service": ""}
    )
    assert snapshot == SnapshotView()


def test_first_snapshot_is_only_a_baseline() -> None:
    feed = EventFeed()
    assert feed.observe(view(chat(1)), NOW) == []
    assert feed.events == ()


def test_chat_added_and_removed() -> None:
    feed = EventFeed()
    feed.observe(view(chat(1), chat(2)), NOW)
    found = feed.observe(view(chat(1), chat(3)), NOW)
    assert [(e.key, e.title, e.tone, e.icon) for e in found] == [
        ("feed.chat_added", "Chat 3", "info", "plus"),
        ("feed.chat_removed", "Chat 2", "muted", "minus"),
    ]
    assert feed.events == tuple(reversed(found))


@pytest.mark.parametrize(
    ("phase", "key"),
    [
        (PHASE_PAUSED, "feed.paused"),
        (PHASE_NO_ACCESS, "feed.no_access"),
        ("starting", None),
    ],
)
def test_phase_changes(phase: str, key: str | None) -> None:
    feed = EventFeed()
    start = "starting" if phase != "starting" else PHASE_LIVE
    feed.observe(view(chat(phase=start)), NOW)
    found = feed.observe(view(chat(phase=phase)), NOW)
    assert [e.key for e in found] == ([key] if key else [])


def test_going_live_is_news() -> None:
    feed = EventFeed()
    feed.observe(view(chat(phase="starting")), NOW)
    assert [e.key for e in feed.observe(view(chat(phase=PHASE_LIVE)), NOW)] == ["feed.live"]


@pytest.mark.parametrize(
    ("state", "key"),
    [
        (BackfillState.RUNNING, "feed.backfill_running"),
        (BackfillState.DONE, "feed.backfill_done"),
        (BackfillState.PAUSED, "feed.backfill_paused"),
        (BackfillState.DISK_STOPPED, "feed.backfill_disk"),
        (BackfillState.RETRYING, "feed.backfill_retrying"),
        (BackfillState.NO_ACCESS, "feed.no_access"),
        (BackfillState.WAITING, None),
    ],
)
def test_backfill_state_changes(state: BackfillState, key: str | None) -> None:
    feed = EventFeed()
    feed.observe(view(chat()), NOW)
    found = feed.observe(view(chat(backfill=BackfillView(state))), NOW)
    assert [e.key for e in found] == ([key] if key else [])


def test_same_state_is_not_repeated() -> None:
    feed = EventFeed()
    running = chat(backfill=BackfillView(BackfillState.RUNNING))
    feed.observe(view(running), NOW)
    assert feed.observe(view(running), NOW) == []


def test_no_access_is_reported_once_when_phase_and_backfill_agree() -> None:
    feed = EventFeed()
    feed.observe(view(chat()), NOW)
    both = chat(phase=PHASE_NO_ACCESS, backfill=BackfillView(BackfillState.NO_ACCESS))
    assert [e.key for e in feed.observe(view(both), NOW)] == ["feed.no_access"]


def test_phase_and_backfill_events_can_both_fire() -> None:
    feed = EventFeed()
    feed.observe(view(chat(phase="starting")), NOW)
    both = chat(phase=PHASE_LIVE, backfill=BackfillView(BackfillState.RUNNING))
    assert [e.key for e in feed.observe(view(both), NOW)] == [
        "feed.live",
        "feed.backfill_running",
    ]


def test_error_events() -> None:
    feed = EventFeed()
    feed.observe(view(), NOW)
    errors = (ServiceError("worker:1", "x"), ServiceError("resolve:a", "y"))
    found = feed.observe(view(errors=errors), NOW)
    assert [e.key for e in found] == ["feed.error_resolve", "feed.error"]
    assert feed.observe(view(errors=errors), NOW) == []
    cleared = feed.observe(view(errors=errors[1:]), NOW)
    assert [e.key for e in cleared] == ["feed.error_cleared"]
    assert cleared[0].tone == "success"


def test_feed_keeps_only_the_newest_events() -> None:
    feed = EventFeed(limit=3)
    feed.observe(view(), NOW)
    for number in range(1, 6):
        feed.observe(view(*(chat(n) for n in range(1, number + 1))), NOW)
    assert [event.title for event in feed.events] == ["Chat 5", "Chat 4", "Chat 3"]
    assert MAX_EVENTS == 50


def test_timezone_is_irrelevant_to_events() -> None:
    feed = EventFeed()
    moment = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3)))
    feed.observe(view(), moment)
    assert feed.observe(view(chat()), moment)[0].at == moment
