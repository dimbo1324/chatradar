# pyright: reportPrivateUsage=false
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from chatimport import commands
from chatimport.commands import ServiceCommands
from chatimport.control import CommandResult
from chatimport.ports import ChatImportError

if TYPE_CHECKING:
    from collections.abc import Mapping


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ServiceCommands:
    async def refuse(_: ServiceCommands, __: Mapping[str, Any]) -> CommandResult:
        raise ChatImportError("not tracked")

    async def crash(_: ServiceCommands, __: Mapping[str, Any]) -> CommandResult:
        raise RuntimeError("boom")

    async def fine(_: ServiceCommands, __: Mapping[str, Any]) -> CommandResult:
        return CommandResult(True, "fine")

    monkeypatch.setitem(commands._REGISTRY, "t_refuse", refuse)
    monkeypatch.setitem(commands._REGISTRY, "t_crash", crash)
    monkeypatch.setitem(commands._REGISTRY, "t_fine", fine)
    return ServiceCommands(None)  # pyright: ignore[reportArgumentType]


async def test_a_refusal_is_one_info_line_without_a_traceback(
    service: ServiceCommands, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=commands.log.name):
        result = await service.execute("t_refuse", {})

    assert result == CommandResult(False, "ChatImportError: not tracked")
    (record,) = caplog.records
    assert record.levelno == logging.INFO
    assert record.exc_info is None
    assert "t_refuse" in record.getMessage()


async def test_an_unexpected_error_is_logged_with_its_traceback(
    service: ServiceCommands, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=commands.log.name):
        result = await service.execute("t_crash", {})

    assert result == CommandResult(False, "RuntimeError: boom")
    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


async def test_success_and_unknown_names_log_nothing(
    service: ServiceCommands, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=commands.log.name):
        assert (await service.execute("t_fine", {})).ok is True
        unknown = await service.execute("nope", {})

    assert unknown == CommandResult(False, "unknown command: 'nope'")
    assert caplog.records == []
