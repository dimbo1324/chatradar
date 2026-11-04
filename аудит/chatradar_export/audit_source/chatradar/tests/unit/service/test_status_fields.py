from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from chatimport.runtime import BackfillInfo, BackfillSlots, BackfillState, ChatRegistry, ChatStatus
from chatimport.status import STATUS_FILE, StatusWriter
from chatimport.supervisor import Supervisor
from tests.fakes import CHAT_ID, FakeClock, FakeDisk, RecordingNotifier
from tests.unit.service.helpers import StubController

if TYPE_CHECKING:
    from pathlib import Path

NEWEST = datetime(2026, 10, 29, 11, 5, 9, tzinfo=UTC)
CONTACT = datetime(2026, 10, 29, 11, 59, 1, tzinfo=UTC)
RETRY = datetime(2026, 10, 29, 12, 3, 0, tzinfo=UTC)


class Detailed(StubController):
    def status(self) -> ChatStatus:
        base = super().status()
        return ChatStatus(
            chat_id=base.chat_id,
            title=base.title,
            phase=base.phase,
            last_id=base.last_id,
            backfill_done=False,
            oldest_date=None,
            records=base.records,
            paused=False,
            error="FloodWaitError",
            newest_date=NEWEST,
            last_contact_at=CONTACT,
            backfill=BackfillInfo(
                BackfillState.RETRYING, progress=0.25, month="2026-09", retry_at=RETRY, detail="X"
            ),
        )


def writer(tmp_path: Path, registry: ChatRegistry, slots: BackfillSlots) -> StatusWriter:
    clock = FakeClock()
    return StatusWriter(
        tmp_path,
        registry,
        Supervisor(clock, RecordingNotifier()),
        clock=clock,
        disk=FakeDisk(10**10),
        low_watermark_gb=1,
        service_state=lambda: "running",
        slots=slots,
    )


async def test_new_chat_fields_and_slots_reach_the_snapshot(tmp_path: Path) -> None:
    registry = ChatRegistry()
    registry.add(Detailed(CHAT_ID))
    slots = BackfillSlots(2)
    async with slots.acquire(CHAT_ID):
        data = writer(tmp_path, registry, slots).build(0)

    (chat,) = data["chats"]
    assert chat["newest_date"] == "2026-10-29T11:05:09Z"
    assert chat["last_contact_at"] == "2026-10-29T11:59:01Z"
    assert chat["error"] == "FloodWaitError"
    assert chat["backfill"] == {
        "state": "retrying",
        "progress": 0.25,
        "month": "2026-09",
        "retry_at": "2026-10-29T12:03:00Z",
        "detail": "X",
    }
    assert data["backfill"] == {"limit": 2, "active": [CHAT_ID], "waiting": []}


async def test_written_snapshot_round_trips_the_new_fields(tmp_path: Path) -> None:
    registry = ChatRegistry()
    registry.add(Detailed(CHAT_ID))
    await writer(tmp_path, registry, BackfillSlots(1)).write()

    data = json.loads((tmp_path / STATUS_FILE).read_text(encoding="utf-8"))
    assert data["chats"][0]["backfill"]["state"] == "retrying"
    assert data["chats"][0]["newest_date"] == "2026-10-29T11:05:09Z"
    assert data["backfill"] == {"limit": 1, "active": [], "waiting": []}
