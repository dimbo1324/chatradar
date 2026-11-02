"""Shared helpers for the Overview and Chats page tests: a frozen clock and sample snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.gui.models.ticker import shared_ticker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from PySide6.QtWidgets import QApplication

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def iso(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def chat(
    chat_id: int,
    title: str | None = None,
    *,
    phase: str = "live",
    state: str | None = None,
    progress: float | None = None,
    age: float | None = 30.0,
    records: int = 10,
    retry_at: str | None = None,
    month: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if state is not None:
        info["state"] = state
    if progress is not None:
        info["progress"] = progress
    if retry_at is not None:
        info["retry_at"] = retry_at
    if month is not None:
        info["month"] = month
    row: dict[str, Any] = {
        "chat_id": chat_id,
        "title": title if title is not None else f"Chat {chat_id}",
        "phase": phase,
        "records": records,
        "backfill": info,
    }
    if age is not None:
        row["newest_date"] = iso(age)
        row["oldest_date"] = iso(age + 86_400 * 40)
        row["last_contact_at"] = iso(age)
    row.update(extra)
    return row


def snapshot(
    chats: list[dict[str, Any]] | None = None,
    *,
    service: str = "running",
    free_gb: float | None = 200.0,
    low_gb: float | None = 10.0,
    errors: list[dict[str, str]] | None = None,
    active: list[int] | None = None,
    waiting: list[int] | None = None,
) -> dict[str, Any]:
    disk: dict[str, Any] = {"path": "D:/x"}
    if free_gb is not None:
        disk["free_gb"] = free_gb
    if low_gb is not None:
        disk["low_watermark_gb"] = low_gb
    return {
        "service": service,
        "updated_at": iso(5),
        "disk": disk,
        "total_bytes": 5_000_000,
        "backfill": {"limit": 1, "active": active or [], "waiting": waiting or []},
        "chats": chats or [],
        "errors": errors or [],
    }


def everything() -> dict[str, Any]:
    return snapshot(
        [
            chat(1, "Alpha", state="running", progress=0.4, age=5, month="2026-04"),
            chat(2, "Bravo", state="running", age=120),
            chat(3, "Charlie", state="waiting", age=4_000),
            chat(4, "Delta", state="retrying", age=90_000, retry_at=iso(-30), error="boom"),
            chat(12, "Lima", state="retrying", age=100, retry_at=iso(60)),
            chat(5, "Echo", state="done", age=500_000),
            chat(6, "Foxtrot", phase="paused", paused=True, state="paused", age=None),
            chat(7, "Golf", phase="no_access", state="no_access", age=None),
            chat(8, "Hotel", state="disk_stopped", age=3_000_000),
            chat(9, "India", state="idle", age=60),
            chat(10, "Juliet", phase="starting", state="done", age=None),
            chat(11, "Kilo", state="retrying", age=100, retry_at=iso(-30)),
        ],
        active=[1],
        waiting=[3],
    )


@pytest.fixture(autouse=True)
def frozen_clock(qapp: QApplication) -> Iterator[None]:
    ticker = shared_ticker()
    original = ticker.clock
    ticker.clock = lambda: NOW
    yield
    ticker.clock = original
    while ticker.animating:
        ticker.release_animation()
