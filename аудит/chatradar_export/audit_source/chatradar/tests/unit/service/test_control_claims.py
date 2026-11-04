"""At-most-once command execution: claims, malformed files and timeouts (S1, S2, C9)."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from chatimport import control
from chatimport.control import (
    CLAIM_SUFFIX,
    COMMAND_TIMEOUTS,
    DEFAULT_TIMEOUT,
    MAX_COMMAND_BYTES,
    RESULT_SUFFIX,
    CommandResult,
    ControlServer,
    Handler,
    send_command,
)
from tests.unit.service.test_control import (
    RealtimeFakeClock,
    names,
    read_result,
    write_command,
)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Extended-length form on Windows: request and temp names do not fit MAX_PATH here."""
    return Path("\\\\?\\" + str(tmp_path)) if sys.platform == "win32" else tmp_path


def counting(calls: list[dict[str, Any]], result: CommandResult | None = None) -> Handler:
    async def handler(args: dict[str, Any]) -> CommandResult:
        calls.append(args)
        return result or CommandResult(True, "done")

    return handler


def server_for(folder: Path, handlers: dict[str, Handler]) -> ControlServer:
    return ControlServer(folder, handlers, clock=RealtimeFakeClock())


async def test_control_command_runs_once_when_file_cannot_be_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    server = server_for(tmp_path, {"trim": counting(calls)})
    write_command(tmp_path, "trim-x.json", {"id": "x", "command": "trim", "args": {"pct": 25}})
    real_unlink = Path.unlink

    def stubborn(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(CLAIM_SUFFIX) or self.name == "trim-x.json":
            raise PermissionError("held open by a scanner")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", stubborn)

    for _ in range(3):
        await server.process_pending()

    assert calls == [{"pct": 25}]
    assert read_result(tmp_path, "trim-x")["ok"] is True


async def test_command_runs_once_when_result_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[dict[str, Any]] = []
    server = server_for(tmp_path, {"trim": counting(calls)})
    write_command(tmp_path, "trim-y.json", {"command": "trim", "args": {"pct": 25}})
    real_write = control._write_json_atomic  # pyright: ignore[reportPrivateUsage]
    failures = [OSError("disk full")]

    def flaky(path: Path, payload: dict[str, Any]) -> None:
        if failures:
            raise failures.pop()
        real_write(path, payload)

    monkeypatch.setattr(control, "_write_json_atomic", flaky)

    with caplog.at_level(logging.ERROR, logger="chatimport.control"):
        await server.process_pending()
        await server.process_pending()

    assert len(calls) == 1
    assert "could not write a command result" in caplog.text
    assert names(tmp_path) == []


async def test_leftover_claimed_command_is_not_rerun_on_start(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    server = server_for(tmp_path, {"trim": counting(calls)})
    write_command(tmp_path, f".trim-z{CLAIM_SUFFIX}", {"id": "z", "command": "trim"})

    assert server.answer_interrupted() == 1
    await server.process_pending()

    assert calls == []
    result = read_result(tmp_path, "trim-z")
    assert result["ok"] is False
    assert "not run again" in result["message"]
    assert not (tmp_path / f".trim-z{CLAIM_SUFFIX}").exists()


async def test_run_answers_leftover_claims_before_the_first_poll(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    clock = RealtimeFakeClock()
    server = ControlServer(tmp_path, {"trim": counting(calls)}, clock=clock)
    write_command(tmp_path, f".trim-w{CLAIM_SUFFIX}", {"command": "trim"})

    def stop(_seconds: float) -> None:
        raise asyncio.CancelledError

    clock.on_sleep = stop
    with pytest.raises(asyncio.CancelledError):
        await server.run()

    assert calls == []
    assert read_result(tmp_path, "trim-w")["ok"] is False


async def test_control_survives_deeply_nested_command_file(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    server = server_for(tmp_path, {"status": counting(calls)})
    depth = 20_000
    write_command(tmp_path, "a-deep.json", "[" * depth + "]" * depth)
    write_command(tmp_path, "b-ok.json", {"command": "status"})

    await server.process_pending()

    deep = read_result(tmp_path, "a-deep")
    assert deep["ok"] is False
    assert "invalid command file" in deep["message"]
    assert read_result(tmp_path, "b-ok")["ok"] is True
    assert calls == [{}]


async def test_oversized_command_file_is_rejected_without_running(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    server = server_for(tmp_path, {"trim": counting(calls)})
    padding = "x" * MAX_COMMAND_BYTES
    write_command(tmp_path, "big.json", {"command": "trim", "pad": padding})

    await server.process_pending()

    assert calls == []
    result = read_result(tmp_path, "big")
    assert result["ok"] is False
    assert "too large" in result["message"]


async def test_a_busy_command_file_waits_for_the_next_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    server = server_for(tmp_path, {"trim": counting(calls)})
    write_command(tmp_path, "busy.json", {"command": "trim"})
    real_replace = Path.replace
    refusals = [PermissionError("sharing violation")]

    def once_busy(self: Path, target: Path) -> Path:
        if self.name == "busy.json" and refusals:
            raise refusals.pop()
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", once_busy)

    await server.process_pending()
    assert calls == []
    assert (tmp_path / "busy.json").exists()

    await server.process_pending()
    assert calls == [{}]


async def test_a_result_that_is_not_json_is_reported_as_failed(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    odd = CommandResult(True, "fine", {"value": object()})
    server = server_for(tmp_path, {"status": counting(calls, odd)})
    write_command(tmp_path, "s.json", {"id": "s1", "command": "status"})

    await server.process_pending()

    assert read_result(tmp_path, "s") == {
        "id": "s1",
        "ok": False,
        "message": "the result could not be encoded",
        "data": {},
    }


async def test_a_claim_that_vanished_before_cleanup_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def drop_claims() -> None:
        for path in tmp_path.glob(f".*{CLAIM_SUFFIX}"):
            path.unlink()

    async def vanish(args: dict[str, Any]) -> CommandResult:
        drop_claims()
        return CommandResult(True)

    server = server_for(tmp_path, {"c": vanish})
    write_command(tmp_path, "v.json", {"command": "c"})

    await server.process_pending()

    assert read_result(tmp_path, "v")["ok"] is True


async def test_run_keeps_polling_after_an_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = RealtimeFakeClock()
    server = ControlServer(tmp_path, {}, clock=clock)
    attempts = 0

    async def broken() -> int:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("unexpected")

    monkeypatch.setattr(server, "process_pending", broken)

    def stop_after_two(_seconds: float) -> None:
        if attempts >= 2:
            raise asyncio.CancelledError

    clock.on_sleep = stop_after_two
    with pytest.raises(asyncio.CancelledError):
        await server.run()

    assert attempts == 2


def no_sleep(_seconds: float) -> None:
    return None


def fake_time(monkeypatch: pytest.MonkeyPatch, step: float) -> list[float]:
    """`time.monotonic` jumps by `step` per call; returns the list of readings."""
    readings: list[float] = []

    def monotonic() -> float:
        value = len(readings) * step
        readings.append(value)
        return value

    monkeypatch.setattr(
        "chatimport.control.time", SimpleNamespace(monotonic=monotonic, sleep=no_sleep)
    )
    return readings


@pytest.mark.parametrize(
    ("command", "expected"),
    [*COMMAND_TIMEOUTS.items(), ("status", DEFAULT_TIMEOUT), ("pause", DEFAULT_TIMEOUT)],
)
def test_send_command_waits_longer_for_long_commands(
    folder: Path, monkeypatch: pytest.MonkeyPatch, command: str, expected: float
) -> None:
    fake_time(monkeypatch, step=expected / 4)

    with pytest.raises(TimeoutError, match=f"within {expected:g} s"):
        send_command(folder, command)


def test_timeout_after_the_service_claimed_the_command_says_it_may_still_run(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def claim_it(_seconds: float) -> None:
        for path in folder.glob("trim-*.json"):
            if not path.name.endswith(RESULT_SUFFIX):
                path.replace(path.with_name(f".{path.stem}{CLAIM_SUFFIX}"))

    monkeypatch.setattr(
        "chatimport.control.time", SimpleNamespace(monotonic=time.monotonic, sleep=claim_it)
    )

    with pytest.raises(TimeoutError, match="may still be running"):
        send_command(folder, "trim", {"pct": 25}, timeout=0.05, poll=0.001)

    assert len(list(folder.glob(f".*{CLAIM_SUFFIX}"))) == 1


def test_timeout_when_the_command_file_cannot_be_withdrawn(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(TimeoutError, match="may not be running"):
        send_command(folder, "pause", timeout=0, poll=0.001)


def test_control_exports_the_shared_result_type() -> None:
    from chatimport.commands import CommandResult as Shared

    assert CommandResult is Shared
