from __future__ import annotations

import json
from typing import TYPE_CHECKING

from chatimport import router as router_module
from chatimport.ports import DeletedMessagesEvent
from chatimport.router import UNROUTED_DELETES_FILE, Router, cap_jsonl
from chatimport.runtime import ChatRegistry
from tests.fakes import FakeClock

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_cap_keeps_only_whole_newest_lines(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_bytes(b"".join(f"line {i:03d}\n".encode() for i in range(100)))
    assert not cap_jsonl(path, 10_000, 50)
    assert cap_jsonl(path, 500, 50)
    data = path.read_bytes()
    assert len(data) <= 50
    assert data.endswith(b"line 099\n")
    assert all(line.startswith(b"line ") for line in data.splitlines())


def test_cap_on_an_exact_line_boundary_keeps_that_line(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_bytes(b"aaaa\nbbbb\ncccc\n")
    assert cap_jsonl(path, 10, 10)
    assert path.read_bytes() == b"bbbb\ncccc\n"


async def test_unrouted_deletes_file_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(router_module, "UNROUTED_MAX_BYTES", 2_000)
    monkeypatch.setattr(router_module, "UNROUTED_KEEP_BYTES", 1_000)
    router = Router(ChatRegistry(), tmp_path, clock=FakeClock())
    for i in range(100):
        await router.handle(DeletedMessagesEvent(None, (i, i + 1000)))
    path = tmp_path / UNROUTED_DELETES_FILE
    assert path.stat().st_size <= 2_000
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["msg_ids"] == [99, 1099]
    assert all(json.loads(line)["chat_id"] is None for line in lines)
