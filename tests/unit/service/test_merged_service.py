from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import merged_service
from chatimport.commands import ExportAllArgs
from chatimport.config import MergedConfig
from chatimport.merged_export import merged_path
from chatimport.merged_service import TICK_SECONDS, MergedExporter
from chatimport.ports import ChatImportError
from chatimport.status import format_status_lines
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import load_state, new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import NOW, FakeClock, msg
from tests.unit.service.harness import make_env

if TYPE_CHECKING:
    from pathlib import Path


def add_message(root: Path, msg_id: int, chat_id: int = 1) -> None:
    folder = root / chat_folder_name("Chat", chat_id)
    writer = ChunkWriter(folder, 10**9, clock=lambda: NOW)
    state = load_state(folder) or new_state(chat_id, "Chat", None, NOW)
    writer.append(state, [msg(msg_id, chat_id=chat_id)])


class Holder:
    def __init__(self, config: MergedConfig) -> None:
        self.config = config

    def __call__(self) -> MergedConfig:
        return self.config


async def test_disabled_exporter_never_builds(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    exporter = MergedExporter(tmp_path, Holder(MergedConfig()), FakeClock())
    await exporter.tick()
    assert not merged_path(tmp_path, "json").exists()
    assert exporter.snapshot() == {
        "enabled": False,
        "last_built_at": None,
        "path": None,
        "records": 0,
        "bytes": 0,
        "building": False,
        "failed": False,
    }


async def test_timer_builds_at_most_every_interval_and_only_when_changed(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    clock = FakeClock()
    exporter = MergedExporter(tmp_path, Holder(MergedConfig(True, "json", 2, False)), clock)

    await exporter.tick()
    first = exporter.last()
    assert first is not None
    assert first.records == 1

    add_message(tmp_path, 2)
    clock.advance(seconds=60)
    await exporter.tick()
    assert exporter.last() is first

    clock.advance(seconds=60)
    await exporter.tick()
    second = exporter.last()
    assert second is not None
    assert second.records == 2

    clock.advance(minutes=5)
    await exporter.tick()
    assert exporter.last() is second
    snap = exporter.snapshot()
    assert snap["enabled"] is True
    assert snap["records"] == 2
    assert snap["last_built_at"] == "2026-10-29T12:02:00Z"
    assert snap["path"] == str(merged_path(tmp_path, "json"))


async def test_config_changes_apply_without_a_new_exporter(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    holder = Holder(MergedConfig())
    exporter = MergedExporter(tmp_path, holder, FakeClock())
    await exporter.tick()
    assert exporter.last() is None
    holder.config = MergedConfig(True, "jsonl", 1, False)
    await exporter.tick()
    assert merged_path(tmp_path, "jsonl").is_file()


async def test_run_loops_on_the_tick_and_survives_a_failing_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    exporter = MergedExporter(tmp_path, Holder(MergedConfig(True, "json", 1, False)), clock)
    calls: list[int] = []

    def boom(*_a: object, **_k: object) -> None:
        calls.append(1)
        raise OSError("disk full")

    monkeypatch.setattr(merged_service, "build_merged", boom)
    reached = asyncio.Event()
    clock.on_sleep = lambda _s: reached.set() if len(clock.sleeps) >= 3 else None
    task = asyncio.create_task(exporter.run())
    await asyncio.wait_for(reached.wait(), 5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(calls) >= 1
    assert set(clock.sleeps) == {TICK_SECONDS}
    assert "combined file build failed" in caplog.text
    assert exporter.snapshot()["failed"] is True
    assert exporter.building is False


async def test_a_good_build_clears_the_failed_flag_and_skipped_keeps_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_message(tmp_path, 1)
    exporter = MergedExporter(tmp_path, Holder(MergedConfig(True, "json", 1, False)), FakeClock())
    real = merged_service.build_merged

    def broken(*_a: object, **_k: object) -> None:
        raise ZeroDivisionError

    monkeypatch.setattr(merged_service, "build_merged", broken)
    with pytest.raises(ZeroDivisionError):
        await exporter.build()
    monkeypatch.setattr(merged_service, "build_merged", real)
    built = await exporter.build()
    assert exporter.snapshot()["failed"] is False
    skipped = await exporter.build()
    assert skipped.skipped is True
    assert exporter.last() is built


async def test_a_skipped_build_is_remembered_when_nothing_else_is(tmp_path: Path) -> None:
    add_message(tmp_path, 1)
    config = Holder(MergedConfig(True, "json", 1, False))
    await MergedExporter(tmp_path, config, FakeClock()).build()
    second = MergedExporter(tmp_path, config, FakeClock())
    again = await second.build()
    assert again.skipped
    assert second.last() is again


def test_args_parse() -> None:
    assert ExportAllArgs.parse({}) == ExportAllArgs(None, None)
    assert ExportAllArgs.parse({"format": "jsonl", "names": 0}) == ExportAllArgs("jsonl", False)
    with pytest.raises(ChatImportError, match="format must be one of"):
        ExportAllArgs.parse({"format": "xml"})


async def test_export_all_command_builds_through_the_service(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    add_message(env.ctx.root, 1)
    env.start()
    await env.wait_running()
    result = await env.app.execute("export_all", {"format": "jsonl", "names": True})
    status = await env.app.execute("status", {})
    await env.stop()
    assert result.ok
    assert result.data["records"] == 1
    assert result.message.endswith("(1 records)")
    assert (env.ctx.root / "_exports" / "all_chats.jsonl").is_file()
    assert status.data["merged"]["records"] == 1
    assert status.data["merged"]["building"] is False


async def test_export_all_command_refuses_a_bad_format(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    result = await env.app.execute("export_all", {"format": "xml"})
    assert result.ok is False


async def test_enabled_service_builds_the_file_on_its_own(tmp_path: Path) -> None:
    env = make_env(tmp_path, config={"merged": {"enabled": True, "every_minutes": 1}})
    add_message(env.ctx.root, 1)
    env.start()
    await env.wait_running()
    await env.clock.advance(5)
    for _ in range(200):
        if merged_path(env.ctx.root, "json").is_file():
            break
        await asyncio.sleep(0.01)
    await env.stop()
    assert merged_path(env.ctx.root, "json").is_file()


def test_status_lines_show_the_combined_file() -> None:
    base: dict[str, Any] = {"chats": [], "total_bytes": 0, "disk": {"free_gb": 1}}
    assert len(format_status_lines(base)) == 1
    off = {**base, "merged": {"enabled": False, "last_built_at": None}}
    assert len(format_status_lines(off)) == 1
    on = {**base, "merged": {"enabled": True, "last_built_at": None, "records": 0}}
    assert format_status_lines(on)[1] == "combined file: 0 records, built never"
    built = {
        **base,
        "merged": {"enabled": True, "last_built_at": "2026-10-29T12:00:00Z", "records": 7},
    }
    assert format_status_lines(built)[1] == "combined file: 7 records, built 2026-10-29T12:00:00Z"
    busy = {**base, "merged": {"enabled": True, "building": True, "records": 7}}
    assert format_status_lines(busy)[1] == "combined file: 7 records, building"
