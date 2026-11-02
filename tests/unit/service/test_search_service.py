# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import search_service
from chatimport.config import SearchConfig
from chatimport.runtime import ChatRegistry
from chatimport.search_db import database_path
from chatimport.search_index import open_reader
from chatimport.search_indexer import StepResult
from chatimport.search_service import BUSY_PAUSE_SECONDS, SearchIndexer
from chatimport.search_types import IndexState, SearchQuery
from chatimport.status import StatusWriter, format_status_lines
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import load_state, new_state
from chatimport.storage.writer import ChunkWriter
from chatimport.supervisor import Supervisor
from tests.fakes import NOW, FakeClock, FakeDisk, RecordingNotifier, msg
from tests.unit.service.harness import make_env

if TYPE_CHECKING:
    from pathlib import Path

READY_SNAPSHOT = {
    "enabled": True,
    "state": "ready",
    "indexed": 2,
    "total": 2,
    "updated_at": "2026-10-29T12:00:00Z",
}


def add_message(root: Path, msg_id: int, chat_id: int = 1) -> None:
    folder = root / chat_folder_name("Chat", chat_id)
    writer = ChunkWriter(folder, 10**9, clock=lambda: NOW)
    state = load_state(folder) or new_state(chat_id, "Chat", None, NOW)
    writer.append(state, [msg(msg_id, chat_id=chat_id, text=f"hello {msg_id}")])


class Holder:
    def __init__(self, config: SearchConfig) -> None:
        self.config = config

    def __call__(self) -> SearchConfig:
        return self.config


async def drain(indexer: SearchIndexer) -> int:
    steps = 0
    while await indexer.tick():
        steps += 1
    return steps


def count_hits(root: Path, text: str) -> int:
    reader = open_reader(root)
    assert reader is not None
    try:
        return reader.search(SearchQuery(text)).total
    finally:
        reader.close()


async def test_a_disabled_indexer_never_touches_the_disk(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig(False, 5)), FakeClock())
    assert await indexer.tick() is False
    assert not database_path(tmp_path).exists()
    assert indexer.snapshot() == {
        "enabled": False,
        "state": "disabled",
        "indexed": 0,
        "total": 0,
        "updated_at": None,
    }


def test_the_snapshot_before_the_first_tick_says_building(tmp_path: Path) -> None:
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    assert indexer.snapshot() == {
        "enabled": True,
        "state": "building",
        "indexed": 0,
        "total": 0,
        "updated_at": None,
    }


async def test_ticks_build_the_index_and_report_progress(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    add_message(tmp_path, 2)
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    try:
        assert await drain(indexer) == 1
        assert indexer.snapshot() == READY_SNAPSHOT
        assert count_hits(tmp_path, "hello") == 2
        assert await indexer.tick() is False
    finally:
        indexer.close()


async def test_switching_the_indexer_off_frees_the_file_and_on_builds_again(
    tmp_path: Path,
) -> None:
    add_message(tmp_path, 1)
    holder = Holder(SearchConfig())
    indexer = SearchIndexer(tmp_path, holder, FakeClock())
    try:
        await drain(indexer)
        holder.config = SearchConfig(False, 5)
        assert await indexer.tick() is False
        assert indexer.snapshot()["state"] == "disabled"
        database_path(tmp_path).unlink()
        holder.config = SearchConfig()
        await drain(indexer)
        assert indexer.snapshot()["state"] == "ready"
        assert count_hits(tmp_path, "hello") == 1
    finally:
        indexer.close()


async def test_without_fts5_the_indexer_stays_off_and_warns_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    add_message(tmp_path, 1)
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    monkeypatch.setattr(search_service, "fts5_trigram_available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="chatimport.search_service"):
        assert await indexer.tick() is False
        assert await indexer.tick() is False
    assert len([r for r in caplog.records if "FTS5" in r.getMessage()]) == 1
    assert indexer.snapshot()["enabled"] is True
    assert indexer.snapshot()["state"] == "disabled"
    assert not database_path(tmp_path).exists()

    monkeypatch.setattr(search_service, "fts5_trigram_available", lambda: True)
    try:
        await drain(indexer)
        assert indexer.snapshot()["state"] == "ready"
    finally:
        indexer.close()


async def test_a_missing_data_folder_is_waited_for(tmp_path: Path) -> None:
    root = tmp_path / "later"
    indexer = SearchIndexer(root, Holder(SearchConfig()), FakeClock())
    try:
        assert await indexer.tick() is False
        assert not root.exists()
        assert indexer.snapshot()["state"] == "building"
        root.mkdir()
        add_message(root, 1)
        await drain(indexer)
        assert indexer.snapshot()["state"] == "ready"
        assert indexer.snapshot()["indexed"] == 1
    finally:
        indexer.close()


async def test_repeated_failures_delete_the_index_and_start_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resets: list[Path] = []

    def broken(_root: Path) -> None:
        raise OSError("cannot open")

    monkeypatch.setattr(search_service, "reset_index", resets.append)
    monkeypatch.setattr(search_service, "open_writer", broken)
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    for _ in range(2):
        with pytest.raises(OSError, match="cannot open"):
            await indexer.tick()
    assert resets == []
    with pytest.raises(OSError, match="cannot open"):
        await indexer.tick()
    assert resets == [tmp_path]
    assert indexer.snapshot()["indexed"] == 0
    with pytest.raises(OSError, match="cannot open"):
        await indexer.tick()
    assert resets == [tmp_path]


async def test_a_success_resets_the_failure_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resets: list[Path] = []
    outcomes = iter(["fail", "fail", "ok", "fail", "fail"])

    def scripted() -> StepResult:
        if next(outcomes) == "fail":
            raise OSError("scripted")
        return StepResult(False, IndexState.READY, 0, 0, None)

    monkeypatch.setattr(search_service, "reset_index", resets.append)
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    monkeypatch.setattr(indexer, "_work", scripted)
    for _ in range(2):
        with pytest.raises(OSError, match="scripted"):
            await indexer.tick()
    assert await indexer.tick() is False
    for _ in range(2):
        with pytest.raises(OSError, match="scripted"):
            await indexer.tick()
    assert resets == []


async def test_a_damaged_file_is_replaced_and_rebuilt(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    add_message(tmp_path, 2)
    first = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    await drain(first)
    first.close()
    database_path(tmp_path).write_bytes(b"this is not a database " * 50)

    second = SearchIndexer(tmp_path, Holder(SearchConfig()), FakeClock())
    try:
        await drain(second)
        assert second.snapshot() == READY_SNAPSHOT
        assert count_hits(tmp_path, "hello") == 2
    finally:
        second.close()


async def test_run_pauses_briefly_while_busy_then_waits_the_interval(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    clock = FakeClock()
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig(True, 5)), clock)
    reached = asyncio.Event()
    clock.on_sleep = lambda _s: reached.set() if len(clock.sleeps) >= 3 else None
    task = asyncio.create_task(indexer.run())
    await asyncio.wait_for(reached.wait(), 10)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert clock.sleeps[:3] == [BUSY_PAUSE_SECONDS, 5, 5]
    assert indexer.snapshot()["state"] == "ready"
    database_path(tmp_path).unlink()


async def test_run_never_waits_less_than_a_second(tmp_path: Path) -> None:
    clock = FakeClock()
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig(False, 0)), clock)
    reached = asyncio.Event()
    clock.on_sleep = lambda _s: reached.set() if len(clock.sleeps) >= 2 else None
    task = asyncio.create_task(indexer.run())
    await asyncio.wait_for(reached.wait(), 10)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert clock.sleeps[:2] == [1, 1]


async def test_run_survives_failing_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_root: Path) -> None:
        raise OSError("cannot open")

    monkeypatch.setattr(search_service, "open_writer", broken)
    clock = FakeClock()
    indexer = SearchIndexer(tmp_path, Holder(SearchConfig(True, 5)), clock)
    reached = asyncio.Event()
    clock.on_sleep = lambda _s: reached.set() if len(clock.sleeps) >= 3 else None
    with caplog.at_level(logging.ERROR, logger="chatimport.search_service"):
        task = asyncio.create_task(indexer.run())
        await asyncio.wait_for(reached.wait(), 10)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert set(clock.sleeps[:3]) == {5}
    assert "search index update failed" in caplog.text


def test_status_lines_show_the_search_index() -> None:
    base: dict[str, Any] = {"chats": [], "total_bytes": 0, "disk": {"free_gb": 1}}
    assert len(format_status_lines(base)) == 1
    for block in ({}, {"state": "disabled"}, {"state": "missing"}, None):
        assert len(format_status_lines({**base, "search": block})) == 1
    building = {**base, "search": {"state": "building", "indexed": 40, "total": 100}}
    assert format_status_lines(building)[1] == "search index: building, 40 of 100 messages"
    bare = {**base, "search": {"state": "building"}}
    assert format_status_lines(bare)[1] == "search index: building, 0 of 0 messages"
    ready = {**base, "search": {"state": "ready", "indexed": 100, "total": 100}}
    assert format_status_lines(ready)[1] == "search index: ready, 100 messages"
    assert format_status_lines({**base, "search": {"state": "ready"}})[1] == (
        "search index: ready, 0 messages"
    )


def test_the_status_writer_includes_the_search_block_only_when_given(tmp_path: Path) -> None:
    clock = FakeClock()

    def writer(search: Any) -> StatusWriter:
        return StatusWriter(
            tmp_path,
            ChatRegistry(),
            Supervisor(clock, RecordingNotifier()),
            clock=clock,
            disk=FakeDisk(10**10),
            low_watermark_gb=1,
            service_state=lambda: "running",
            search=search,
        )

    assert "search" not in writer(None).build(total_bytes=0)
    block = {"enabled": True, "state": "ready", "indexed": 1, "total": 1, "updated_at": None}
    assert writer(lambda: block).build(total_bytes=0)["search"] == block


async def test_the_running_service_indexes_and_reports_it_in_the_status(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    add_message(env.ctx.root, 1)
    env.start()
    await env.wait_running()

    async def ready() -> bool:
        data = await env.status()
        return data is not None and data["search"]["state"] == "ready"

    await env.until_async(ready)
    data = await env.status()
    runtime = env.app.runtime()
    runtime.config = replace(runtime.config, search=SearchConfig(False, 5))
    switched_off = runtime.search.snapshot()
    await env.stop()

    assert data is not None
    block = data["search"]
    assert (block["enabled"], block["state"], block["indexed"], block["total"]) == (
        True,
        "ready",
        1,
        1,
    )
    assert block["updated_at"].endswith("Z")
    assert count_hits(env.ctx.root, "hello") == 1
    assert (switched_off["enabled"], switched_off["state"]) == (False, "disabled")
    database_path(env.ctx.root).unlink()


async def test_a_service_with_search_off_builds_no_index(tmp_path: Path) -> None:
    env = make_env(tmp_path, config={"search": {"enabled": False}})
    add_message(env.ctx.root, 1)
    env.start()
    await env.wait_running()
    await env.clock.advance(20)
    data = await env.status()
    await env.stop()
    assert data is not None
    assert data["search"]["state"] == "disabled"
    assert data["search"]["enabled"] is False
    assert not database_path(env.ctx.root).exists()
