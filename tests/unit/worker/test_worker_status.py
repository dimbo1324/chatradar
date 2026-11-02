from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from chatimport.runtime import BackfillState
from chatimport.storage.state import PHASE_NO_ACCESS, ChatState, new_state
from chatimport.worker_status import (
    FLOOR_REASON_DISK,
    BackfillSignals,
    backfill_info,
    backfill_progress,
)
from tests.fakes import NOW

RETRY = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def signals(**overrides: object) -> BackfillSignals:
    base = BackfillSignals(
        paused=False, slot_held=False, slot_waiting=False, month=None, retry_at=None, detail=None
    )
    return replace(base, **overrides)  # pyright: ignore[reportArgumentType]


def state_with(**backfill: object) -> ChatState:
    state = new_state(5, "Example", None, NOW)
    return replace(state, backfill=replace(state.backfill, **backfill))  # pyright: ignore[reportArgumentType]


def test_progress_is_complete_when_done() -> None:
    assert backfill_progress(state_with(done=True)) == 1.0


@pytest.mark.parametrize(("head", "oldest"), [(0, 5), (10, 0), (-1, 3), (10, -2)])
def test_progress_is_unknown_without_both_ids(head: int, oldest: int) -> None:
    assert backfill_progress(state_with(head_id=head, oldest_done_id=oldest)) is None


@pytest.mark.parametrize(
    ("head", "oldest", "expected"), [(100, 25, 0.75), (100, 100, 0.0), (100, 150, 0.0)]
)
def test_progress_is_a_clamped_share(head: int, oldest: int, expected: float) -> None:
    assert backfill_progress(state_with(head_id=head, oldest_done_id=oldest)) == expected


def test_done_with_disk_floor_is_disk_stopped() -> None:
    state = replace(state_with(done=True), floor_reason=FLOOR_REASON_DISK)
    info = backfill_info(state, signals())
    assert info.state is BackfillState.DISK_STOPPED
    assert info.progress == 1.0


def test_done_is_done_and_hides_worker_facts() -> None:
    info = backfill_info(state_with(done=True), signals(month="2026-09", detail="x"))
    assert info.state is BackfillState.DONE
    assert info.month is None
    assert info.detail is None


def test_no_access_phase() -> None:
    state = replace(state_with(), phase=PHASE_NO_ACCESS)
    assert backfill_info(state, signals(paused=True)).state is BackfillState.NO_ACCESS


def test_paused_beats_everything_else_when_not_done() -> None:
    info = backfill_info(state_with(), signals(paused=True, retry_at=RETRY, slot_held=True))
    assert info.state is BackfillState.PAUSED


def test_retrying_reports_month_time_and_detail() -> None:
    info = backfill_info(
        state_with(head_id=10, oldest_done_id=5),
        signals(retry_at=RETRY, month="2026-09", detail="flood"),
    )
    assert info.state is BackfillState.RETRYING
    assert (info.month, info.retry_at, info.detail) == ("2026-09", RETRY, "flood")
    assert info.progress == 0.5


def test_running_reports_the_month_but_not_retry_fields() -> None:
    info = backfill_info(state_with(), signals(slot_held=True, month="2026-09", detail="d"))
    assert info.state is BackfillState.RUNNING
    assert info.month == "2026-09"
    assert info.detail is None
    assert info.retry_at is None


def test_waiting_and_idle() -> None:
    assert backfill_info(state_with(), signals(slot_waiting=True)).state is BackfillState.WAITING
    assert backfill_info(state_with(), signals()).state is BackfillState.IDLE


def test_without_state_there_is_no_progress() -> None:
    info = backfill_info(None, signals(slot_held=True, month="2026-09"))
    assert info.state is BackfillState.RUNNING
    assert info.progress is None
    assert backfill_info(None, signals(paused=True)).state is BackfillState.PAUSED
