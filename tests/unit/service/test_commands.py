"""The command registry, the argument objects and `finish` (A4, D15, C12)."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import commands, control
from chatimport.commands import (
    COMMAND_NAMES,
    COMMANDS,
    ChatArgs,
    CheckArgs,
    NoArgs,
    RecheckArgs,
    SetRootArgs,
    TrimArgs,
    finish,
    in_thread,
)
from chatimport.ports import ChatImportError
from tests.unit.service.harness import make_env

if TYPE_CHECKING:
    from pathlib import Path


def test_every_registered_command_is_routable(tmp_path: Path) -> None:
    handlers = make_env(tmp_path).app.build_handlers()

    assert set(control.COMMANDS) == set(handlers) == set(COMMANDS) == set(COMMAND_NAMES)
    assert len(COMMAND_NAMES) == 11


async def test_trim_without_pct_reports_clear_error(tmp_path: Path) -> None:
    result = await make_env(tmp_path).app.execute("trim", {})

    assert result.ok is False
    assert result.message == "ChatImportError: pct is required"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"pct": 25}, TrimArgs(25)),
        ({"pct": " 50 ", "chat": "Beta"}, TrimArgs(50, "Beta")),
        ({"pct": 75, "chat": -5}, TrimArgs(75, -5)),
        ({"pct": 75, "chat": ""}, TrimArgs(75)),
        ({"pct": 75, "chat": True}, TrimArgs(75, "True")),
    ],
)
def test_trim_args_parse(args: dict[str, Any], expected: TrimArgs) -> None:
    assert TrimArgs.parse(args) == expected


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({}, "pct is required"),
        ({"pct": None}, "pct is required"),
        ({"pct": "abc"}, "pct must be a whole number"),
        ({"pct": 1.5}, "pct must be a whole number"),
        ({"pct": True}, "pct must be a whole number"),
        ({"pct": [25]}, "pct must be a whole number"),
    ],
)
def test_trim_args_reject_bad_values(args: dict[str, Any], message: str) -> None:
    with pytest.raises(ChatImportError, match=message):
        TrimArgs.parse(args)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({}, RecheckArgs()),
        ({"days": 3}, RecheckArgs(3)),
        ({"days": "14", "chat": 7}, RecheckArgs(14, 7)),
    ],
)
def test_recheck_args_parse(args: dict[str, Any], expected: RecheckArgs) -> None:
    assert RecheckArgs.parse(args) == expected


@pytest.mark.parametrize(("days", "message"), [(0, "at least 1"), ("soon", "whole number")])
def test_recheck_args_reject_bad_days(days: object, message: str) -> None:
    with pytest.raises(ChatImportError, match=message):
        RecheckArgs.parse({"days": days})


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"path": " D:/Data "}, SetRootArgs("D:/Data")),
        ({"path": "x", "move": 1}, SetRootArgs("x", move=True)),
    ],
)
def test_set_root_args_parse(args: dict[str, Any], expected: SetRootArgs) -> None:
    assert SetRootArgs.parse(args) == expected


@pytest.mark.parametrize("path", [None, "", "   ", 5])
def test_set_root_args_need_a_path(path: object) -> None:
    with pytest.raises(ChatImportError, match="path is required"):
        SetRootArgs.parse({"path": path})


def test_simple_args_parse() -> None:
    assert NoArgs.parse({"anything": 1}) == NoArgs()
    assert ChatArgs.parse({}) == ChatArgs()
    assert CheckArgs.parse({}) == CheckArgs(repair=False)
    assert CheckArgs.parse({"repair": True}) == CheckArgs(repair=True)


async def test_finish_returns_the_result() -> None:
    assert await in_thread(sum, [1, 2, 3]) == 6


async def test_cancelled_finish_waits_for_the_thread_before_reraising() -> None:
    started, release = threading.Event(), threading.Event()
    done: list[str] = []

    def work() -> None:
        started.set()
        release.wait(5)
        done.append("finished")

    task = asyncio.create_task(in_thread(work))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == ["finished"]


async def test_cancelled_finish_reraises_even_if_the_work_failed() -> None:
    gate = asyncio.Event()

    async def failing() -> None:
        await gate.wait()
        raise OSError("boom")

    inner = asyncio.ensure_future(failing())
    outer = asyncio.create_task(finish(inner))
    await asyncio.sleep(0)
    outer.cancel()
    await asyncio.sleep(0)
    gate.set()

    with pytest.raises(asyncio.CancelledError):
        await outer
    assert isinstance(inner.exception(), OSError)


async def test_cancelled_finish_of_a_cancelled_task() -> None:
    inner: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    outer = asyncio.create_task(finish(inner))
    await asyncio.sleep(0)
    outer.cancel()
    await asyncio.sleep(0)
    inner.cancel()

    with pytest.raises(asyncio.CancelledError):
        await outer


def test_registry_is_read_only() -> None:
    with pytest.raises(TypeError):
        COMMANDS["evil"] = COMMANDS["status"]  # type: ignore[index]  # pyright: ignore[reportIndexIssue]
    assert tuple(COMMANDS) == commands.COMMAND_NAMES
