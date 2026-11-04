"""What a chat worker reports about its history download: derived from `state.json` and the
worker's live flags, so the status never keeps a second copy of the truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chatimport.runtime import BackfillInfo, BackfillState
from chatimport.storage.state import PHASE_NO_ACCESS

if TYPE_CHECKING:
    from datetime import datetime

    from chatimport.storage.state import ChatState

FLOOR_REASON_DISK: Final = "disk"


@dataclass(frozen=True, slots=True)
class BackfillSignals:
    """The worker-side facts that `state.json` does not hold."""

    paused: bool
    slot_held: bool
    slot_waiting: bool
    month: str | None
    retry_at: datetime | None
    detail: str | None


def backfill_progress(state: ChatState) -> float | None:
    backfill = state.backfill
    if backfill.done:
        return 1.0
    if backfill.head_id <= 0 or backfill.oldest_done_id <= 0:
        return None
    return min(1.0, max(0.0, (backfill.head_id - backfill.oldest_done_id) / backfill.head_id))


def _kind(state: ChatState | None, signals: BackfillSignals) -> BackfillState:
    if state is not None:
        if state.backfill.done:
            if state.floor_reason == FLOOR_REASON_DISK:
                return BackfillState.DISK_STOPPED
            return BackfillState.DONE
        if state.phase == PHASE_NO_ACCESS:
            return BackfillState.NO_ACCESS
    if signals.paused:
        return BackfillState.PAUSED
    if signals.retry_at is not None:
        return BackfillState.RETRYING
    if signals.slot_held:
        return BackfillState.RUNNING
    if signals.slot_waiting:
        return BackfillState.WAITING
    return BackfillState.IDLE


def backfill_info(state: ChatState | None, signals: BackfillSignals) -> BackfillInfo:
    kind = _kind(state, signals)
    retrying = kind is BackfillState.RETRYING
    return BackfillInfo(
        state=kind,
        progress=backfill_progress(state) if state is not None else None,
        month=signals.month if kind is BackfillState.RUNNING or retrying else None,
        retry_at=signals.retry_at if retrying else None,
        detail=signals.detail if retrying else None,
    )
