from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chatimport.control import (
    COMMANDS,
    RESULT_SUFFIX,
    STALE_RESULT_SECONDS,
    AlreadyRunning,
    CommandResult,
    ControlServer,
    Handler,
    acquire_instance_lock,
    send_command,
    service_running,
)
from chatimport.ports import ChatImportError
from tests.fakes import FakeClock


@pytest.fixture
def ctl(tmp_path: Path) -> Path:
    """The scratch path is deep: use the extended-length form so temp names fit MAX_PATH."""
    folder = tmp_path / "c"
    folder.mkdir()
    return Path("\\\\?\\" + str(folder)) if sys.platform == "win32" else folder


class RealtimeFakeClock(FakeClock):
    """Wall-clock `now` (file mtimes are real) but sleeps only yield."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if self.on_sleep is not None:
            self.on_sleep(seconds)
        await asyncio.sleep(0.005)


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def write_command(folder: Path, name: str, payload: object, *, mtime_ns: int | None = None) -> Path:
    path = folder / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), "utf-8")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def read_result(folder: Path, stem: str) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((folder / f"{stem}{RESULT_SUFFIX}").read_text("utf-8"))
    return value


def make_server(
    folder: Path, handlers: dict[str, Handler] | None = None
) -> tuple[ControlServer, RealtimeFakeClock]:
    clock = RealtimeFakeClock()
    return ControlServer(folder, handlers or {}, clock=clock), clock


def echo_handler(calls: list[tuple[str, dict[str, Any]]], name: str) -> Handler:
    async def handler(args: dict[str, Any]) -> CommandResult:
        calls.append((name, args))
        return CommandResult(True, f"done {name}", {"args": args})

    return handler


async def test_command_runs_result_is_written_and_command_removed(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    server, _ = make_server(tmp_path, {"trim": echo_handler(calls, "trim")})
    write_command(tmp_path, "trim-1.json", {"id": "abc", "command": "trim", "args": {"pct": 50}})

    processed = await server.process_pending()

    assert processed == 1
    assert calls == [("trim", {"pct": 50})]
    assert not (tmp_path / "trim-1.json").exists()
    assert read_result(tmp_path, "trim-1") == {
        "id": "abc",
        "ok": True,
        "message": "done trim",
        "data": {"args": {"pct": 50}},
    }


async def test_no_pending_commands_is_a_cheap_noop(tmp_path: Path) -> None:
    server, _ = make_server(tmp_path)

    assert await server.process_pending() == 0
    assert names(tmp_path) == []


async def test_unknown_command_gets_a_failed_result(tmp_path: Path) -> None:
    server, _ = make_server(tmp_path)
    write_command(tmp_path, "x-1.json", {"id": "i", "command": "format-disk"})

    await server.process_pending()

    result = read_result(tmp_path, "x-1")
    assert result["ok"] is False
    assert "unknown command" in result["message"]
    assert "format-disk" in result["message"]
    assert not (tmp_path / "x-1.json").exists()


@pytest.mark.parametrize(
    "body",
    ["", "{not json", "{", "﻿{}", "\x00\x00"],
)
async def test_invalid_json_gets_a_failed_result_and_is_removed(tmp_path: Path, body: str) -> None:
    server, _ = make_server(tmp_path)
    write_command(tmp_path, "bad-1.json", body)

    await server.process_pending()

    result = read_result(tmp_path, "bad-1")
    assert result["ok"] is False
    assert "invalid command file" in result["message"]
    assert result["id"] == "bad-1"
    assert not (tmp_path / "bad-1.json").exists()


@pytest.mark.parametrize("body", ["[]", "[1, 2]", '"text"', "42", "null", "true"])
async def test_json_that_is_not_an_object_is_rejected(tmp_path: Path, body: str) -> None:
    server, _ = make_server(tmp_path)
    write_command(tmp_path, "list-1.json", body)

    await server.process_pending()

    result = read_result(tmp_path, "list-1")
    assert result["ok"] is False
    assert "not a JSON object" in result["message"]


async def test_non_utf8_bytes_are_rejected_not_raised(tmp_path: Path) -> None:
    server, _ = make_server(tmp_path)
    (tmp_path / "raw-1.json").write_bytes(b'{"command": "\xff\xfe"}')

    await server.process_pending()

    assert read_result(tmp_path, "raw-1")["ok"] is False
    assert not (tmp_path / "raw-1.json").exists()


@pytest.mark.parametrize("args", ["text", [1], 5, True])
async def test_args_that_are_not_an_object_are_rejected(tmp_path: Path, args: object) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    server, _ = make_server(tmp_path, {"trim": echo_handler(calls, "trim")})
    write_command(tmp_path, "t-1.json", {"id": "i", "command": "trim", "args": args})

    await server.process_pending()

    assert calls == []
    result = read_result(tmp_path, "t-1")
    assert result["ok"] is False
    assert "args is not an object" in result["message"]
    assert result["id"] == "i"


@pytest.mark.parametrize("args", [None, {}, 0, "", False, []])
async def test_missing_or_falsy_args_mean_empty_args(tmp_path: Path, args: object) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    server, _ = make_server(tmp_path, {"pause": echo_handler(calls, "pause")})
    write_command(tmp_path, "p-1.json", {"id": "i", "command": "pause", "args": args})

    await server.process_pending()

    assert calls == [("pause", {})]


async def test_missing_command_field_is_reported_as_unknown(tmp_path: Path) -> None:
    server, _ = make_server(tmp_path)
    write_command(tmp_path, "n-1.json", {"id": "i"})

    await server.process_pending()

    assert read_result(tmp_path, "n-1")["ok"] is False


async def test_handler_exception_becomes_a_failed_result_and_others_still_run(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def boom(args: dict[str, Any]) -> CommandResult:
        raise ValueError("bad pct")

    server, _ = make_server(tmp_path, {"trim": boom, "pause": echo_handler(calls, "pause")})
    write_command(tmp_path, "a-1.json", {"id": "1", "command": "trim"}, mtime_ns=1_000_000_000)
    write_command(tmp_path, "b-1.json", {"id": "2", "command": "pause"}, mtime_ns=2_000_000_000)

    await server.process_pending()

    assert read_result(tmp_path, "a-1") == {
        "id": "1",
        "ok": False,
        "message": "ValueError: bad pct",
        "data": {},
    }
    assert read_result(tmp_path, "b-1")["ok"] is True


async def test_cancellation_inside_a_handler_is_not_swallowed(tmp_path: Path) -> None:
    async def cancelled(args: dict[str, Any]) -> CommandResult:
        raise asyncio.CancelledError

    server, _ = make_server(tmp_path, {"trim": cancelled})
    write_command(tmp_path, "c-1.json", {"id": "1", "command": "trim"})

    with pytest.raises(asyncio.CancelledError):
        await server.process_pending()


async def test_commands_run_oldest_first_by_mtime_then_by_name(tmp_path: Path) -> None:
    order: list[str] = []

    async def record(args: dict[str, Any]) -> CommandResult:
        order.append(args["n"])
        return CommandResult(True)

    server, _ = make_server(tmp_path, {"c": record})
    base = time.time_ns()
    write_command(tmp_path, "z.json", {"command": "c", "args": {"n": "z"}}, mtime_ns=base)
    write_command(tmp_path, "b.json", {"command": "c", "args": {"n": "b"}}, mtime_ns=base + 10**9)
    write_command(tmp_path, "a.json", {"command": "c", "args": {"n": "a"}}, mtime_ns=base + 10**9)
    write_command(tmp_path, "m.json", {"command": "c", "args": {"n": "m"}}, mtime_ns=base - 10**9)

    await server.process_pending()

    assert order == ["m", "z", "a", "b"]


async def test_result_files_temp_files_and_foreign_files_are_not_commands(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    server, _ = make_server(tmp_path, {"trim": echo_handler(calls, "trim")})
    body = {"id": "i", "command": "trim"}
    write_command(tmp_path, f"old{RESULT_SUFFIX}", body)
    write_command(tmp_path, ".hidden.json", body)
    write_command(tmp_path, "cmd.json.tmp", body)
    write_command(tmp_path, "note.txt", body)
    write_command(tmp_path, ".trim-1.json.deadbeef.tmp", body)
    write_command(tmp_path, "real.json", body)

    processed = await server.process_pending()

    assert processed == 1
    assert len(calls) == 1
    assert (tmp_path / "note.txt").exists()
    assert (tmp_path / ".hidden.json").exists()
    assert (tmp_path / "cmd.json.tmp").exists()


async def test_a_directory_named_like_a_command_does_not_crash_the_loop(
    tmp_path: Path,
) -> None:
    server, _ = make_server(tmp_path)
    (tmp_path / "dir.json").mkdir()

    await server.process_pending()

    assert (tmp_path / "dir.json").is_dir()


async def test_result_without_stale_age_is_kept(tmp_path: Path) -> None:
    server, _ = make_server(tmp_path)
    fresh = write_command(tmp_path, f"f{RESULT_SUFFIX}", {"ok": True})

    await server.process_pending()

    assert fresh.exists()


async def test_stale_results_are_removed_only_past_ten_minutes(tmp_path: Path) -> None:
    server, clock = make_server(tmp_path)
    now_ns = time.time_ns()
    old = write_command(
        tmp_path, f"old{RESULT_SUFFIX}", {}, mtime_ns=now_ns - (STALE_RESULT_SECONDS + 30) * 10**9
    )
    edge = write_command(
        tmp_path, f"edge{RESULT_SUFFIX}", {}, mtime_ns=now_ns - (STALE_RESULT_SECONDS - 30) * 10**9
    )

    await server.process_pending()

    assert not old.exists()
    assert edge.exists()
    assert clock.sleeps == []


async def test_a_freshly_written_result_survives_even_if_the_clock_runs_late(
    tmp_path: Path,
) -> None:
    clock = FakeClock(datetime.now(UTC))
    server = ControlServer(tmp_path, {}, clock=clock)
    await server.process_pending()
    result = write_command(tmp_path, f"r{RESULT_SUFFIX}", {})
    clock.advance(seconds=STALE_RESULT_SECONDS - 5)

    await server.process_pending()
    assert result.exists()
    clock.advance(seconds=10)
    await server.process_pending()
    assert not result.exists()


async def test_run_creates_the_folder_polls_and_survives_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "control" / "nested"
    server, clock = make_server(folder)
    attempts = 0
    real = server.process_pending

    async def flaky() -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("scan failed")
        return await real()

    monkeypatch.setattr(server, "process_pending", flaky)

    def stop_after_three(_seconds: float) -> None:
        if attempts >= 3:
            raise asyncio.CancelledError

    clock.on_sleep = stop_after_three

    with pytest.raises(asyncio.CancelledError):
        await server.run()

    assert folder.is_dir()
    assert attempts == 3
    assert clock.sleeps == [1.0, 1.0, 1.0]


async def test_send_command_end_to_end_against_a_running_server(ctl: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    server, _ = make_server(ctl, {"trim": echo_handler(calls, "trim")})
    task = asyncio.create_task(server.run())
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(send_command, ctl, "trim", {"pct": 25}, timeout=10, poll=0.005),
            15,
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert result == CommandResult(True, "done trim", {"args": {"pct": 25}})
    assert calls == [("trim", {"pct": 25})]
    assert names(ctl) == []


async def test_send_command_failed_result_carries_the_message(ctl: Path) -> None:
    server, _ = make_server(ctl)
    task = asyncio.create_task(server.run())
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(send_command, ctl, "nope", timeout=10, poll=0.005), 15
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert result.ok is False
    assert "unknown command" in result.message


async def test_two_concurrent_clients_get_their_own_answers(ctl: Path) -> None:
    async def echo(args: dict[str, Any]) -> CommandResult:
        return CommandResult(True, str(args["n"]))

    server, _ = make_server(ctl, {"c": echo})
    task = asyncio.create_task(server.run())
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(
                    asyncio.to_thread(send_command, ctl, "c", {"n": n}, timeout=10, poll=0.005)
                    for n in range(5)
                )
            ),
            15,
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert sorted(r.message for r in results) == ["0", "1", "2", "3", "4"]


def test_send_command_timeout_removes_its_own_command_file(ctl: Path) -> None:
    other = write_command(ctl, "someone-else.json", {"command": "x"})

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="no answer to 'trim'"):
        send_command(ctl, "trim", timeout=0.05, poll=0.01)

    assert time.monotonic() - started < 2
    assert [p.name for p in ctl.iterdir()] == [other.name]


def test_send_command_creates_the_control_folder(ctl: Path) -> None:
    folder = ctl / "a" / "control"

    with pytest.raises(TimeoutError):
        send_command(folder, "trim", timeout=0, poll=0.001)

    assert folder.is_dir()


def test_send_command_writes_the_documented_request_format(
    ctl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder: dict[str, Any] = {}

    def spy_sleep(_seconds: float) -> None:
        for path in ctl.glob("*.json"):
            holder["name"] = path.name
            holder["body"] = json.loads(path.read_text("utf-8"))

    monkeypatch.setattr(
        "chatimport.control.time", SimpleNamespace(monotonic=time.monotonic, sleep=spy_sleep)
    )
    with pytest.raises(TimeoutError):
        send_command(ctl, "trim", {"pct": 50, "chat": None}, timeout=0.02, poll=0.001)

    assert holder["name"].startswith("trim-")
    assert holder["body"]["command"] == "trim"
    assert holder["body"]["args"] == {"pct": 50, "chat": None}
    assert holder["name"] == f"trim-{holder['body']['id']}.json"


def test_send_command_reads_a_prewritten_result_and_deletes_it(
    ctl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    fixed = uuid.UUID(int=7)
    monkeypatch.setattr("chatimport.control.uuid.uuid4", lambda: fixed)
    stem = f"status-{fixed.hex}"
    write_command(
        ctl,
        f"{stem}{RESULT_SUFFIX}",
        {"id": fixed.hex, "ok": True, "message": "hi", "data": {"k": 1}},
    )

    result = send_command(ctl, "status", timeout=1, poll=0.001)

    assert result == CommandResult(True, "hi", {"k": 1})
    assert not (ctl / f"{stem}{RESULT_SUFFIX}").exists()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, CommandResult(False, "", {})),
        ({"ok": 1, "message": 5, "data": [1]}, CommandResult(True, "5", {})),
        ({"ok": None, "data": None}, CommandResult(False, "", {})),
        ({"ok": True, "message": "m", "data": {"a": [1]}}, CommandResult(True, "m", {"a": [1]})),
    ],
)
def test_send_command_tolerates_odd_result_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
    expected: CommandResult,
) -> None:
    import uuid

    fixed = uuid.UUID(int=9)
    monkeypatch.setattr("chatimport.control.uuid.uuid4", lambda: fixed)
    write_command(tmp_path, f"x-{fixed.hex}{RESULT_SUFFIX}", payload)

    assert send_command(tmp_path, "x", timeout=1, poll=0.001) == expected


def test_send_command_keeps_waiting_while_the_result_is_garbage(
    ctl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    fixed = uuid.UUID(int=11)
    monkeypatch.setattr("chatimport.control.uuid.uuid4", lambda: fixed)
    write_command(ctl, f"x-{fixed.hex}{RESULT_SUFFIX}", "{half a json")

    with pytest.raises(TimeoutError):
        send_command(ctl, "x", timeout=0.05, poll=0.01)


def test_command_result_defaults_are_not_shared() -> None:
    first, second = CommandResult(True), CommandResult(True)

    first.data["x"] = 1

    assert second.data == {}
    assert first.message == ""


def test_commands_constant_lists_every_documented_name() -> None:
    assert set(COMMANDS) == {
        "trim",
        "pause",
        "resume",
        "recheck",
        "status",
        "reload_config",
        "set_root",
        "shutdown",
        "refetch",
        "deeper",
        "check",
    }
    assert len(set(COMMANDS)) == len(COMMANDS)


def test_service_running_is_false_for_a_free_lock_and_creates_the_folder(
    tmp_path: Path,
) -> None:
    lock_file = tmp_path / "missing" / "dir" / "chatimport.lock"

    assert service_running(lock_file) is False
    assert service_running(lock_file) is False
    assert lock_file.parent.is_dir()


def test_second_acquire_raises_already_running_and_release_allows_it_again(
    tmp_path: Path,
) -> None:
    lock_file = tmp_path / "nested" / "chatimport.lock"

    first = acquire_instance_lock(lock_file)
    try:
        assert service_running(lock_file) is True
        with pytest.raises(AlreadyRunning, match="already running"):
            acquire_instance_lock(lock_file)
    finally:
        first.release()

    assert service_running(lock_file) is False
    second = acquire_instance_lock(lock_file)
    second.release()


def test_failed_second_acquire_does_not_steal_or_release_the_first_lock(
    tmp_path: Path,
) -> None:
    lock_file = tmp_path / "l.lock"
    first = acquire_instance_lock(lock_file)
    try:
        for _ in range(3):
            with pytest.raises(AlreadyRunning):
                acquire_instance_lock(lock_file)
        assert service_running(lock_file) is True
    finally:
        first.release()


def test_already_running_is_an_expected_handled_error() -> None:
    assert issubclass(AlreadyRunning, ChatImportError)
