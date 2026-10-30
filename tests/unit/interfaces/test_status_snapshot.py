from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import status as status_module
from chatimport.runtime import ChatRegistry
from chatimport.status import (
    STATUS_FILE,
    StatusWriter,
    format_chat_lines,
    format_status_lines,
    read_snapshot,
)
from chatimport.supervisor import Supervisor
from tests.fakes import FakeClock, FakeDisk, RecordingNotifier
from tests.unit.service.helpers import StubController

if TYPE_CHECKING:
    from pathlib import Path


def writer(root: Path, registry: ChatRegistry | None = None) -> StatusWriter:
    clock = FakeClock()
    return StatusWriter(
        root,
        registry or ChatRegistry(),
        Supervisor(clock, RecordingNotifier()),
        clock=clock,
        disk=FakeDisk(10 * 1024**3),
        low_watermark_gb=15,
        service_state=lambda: "running",
    )


async def test_snapshot_roundtrip_through_reader(tmp_path: Path) -> None:
    registry = ChatRegistry()
    registry.add(StubController(-5, tmp_path / "chat", title="\u0427\u0430\u0442"))
    status_writer = writer(tmp_path, registry)
    await status_writer.write()

    data = read_snapshot(tmp_path)

    assert data is not None
    assert data == json.loads(json.dumps(status_writer.build(data["total_bytes"])))
    assert format_status_lines(data)[0].startswith("1 chat")
    assert format_chat_lines(data) == [
        "  -5 \u0427\u0430\u0442: live, last_id 0, backfill done, 0 records"
    ]


@pytest.mark.parametrize("content", ["{broken", "[1]", "null"])
def test_read_snapshot_of_a_broken_file_is_none(tmp_path: Path, content: str) -> None:
    (tmp_path / STATUS_FILE).write_text(content, encoding="utf-8")
    assert read_snapshot(tmp_path) is None


def test_read_snapshot_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert read_snapshot(tmp_path) is None


def test_chat_lines_mark_paused_and_finished_chats() -> None:
    data: dict[str, Any] = {
        "chats": [{"chat_id": 1, "phase": "live", "backfill_done": True, "paused": True}]
    }
    assert format_chat_lines(data) == ["  1 : live, last_id None, backfill done, 0 records, paused"]
    assert format_chat_lines({}) == []


def test_status_total_does_not_enter_media_dirs(tmp_path: Path) -> None:
    chat = tmp_path / "chat_-1"
    (chat / "media" / "2026-10").mkdir(parents=True)
    (chat / "media" / "2026-10" / "7.jsonl").write_bytes(b"x" * 50)
    (tmp_path / "_exports").mkdir()
    (tmp_path / "_exports" / "old.jsonl").write_bytes(b"x" * 50)
    (chat / "2026-10_001.jsonl").write_bytes(b"1234")

    assert writer(tmp_path).build()["total_bytes"] == 4


async def test_build_on_demand_reuses_the_last_periodic_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "2026-10_001.jsonl").write_bytes(b"123")
    status_writer = writer(tmp_path)
    await status_writer.write()

    def no_walk(_path: str) -> Any:
        raise AssertionError("walked the tree")

    monkeypatch.setattr(status_module, "os", SimpleNamespace(scandir=no_walk))

    assert status_writer.build()["total_bytes"] == 3
