from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from chatimport import cli

if TYPE_CHECKING:
    from typer.testing import Result

    from tests.unit.interfaces.conftest import Env


class Launches:
    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.code = 0

    def __call__(self, ctx: Any, *, start_hidden: bool = False) -> int:
        self.calls.append(start_hidden)
        return self.code


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> Launches:
    from chatimport.gui import launch

    fake = Launches()
    monkeypatch.setattr(launch, "run_gui", fake)
    return fake


def invoke(env: Env, *args: str) -> Result:
    return env.runner.invoke(cli.app, list(args))


def test_window_opens_the_window(env: Env, launches: Launches) -> None:
    result = invoke(env, "window")
    assert result.exit_code == 0
    assert launches.calls == [False]


def test_window_hidden_starts_in_the_tray(env: Env, launches: Launches) -> None:
    assert invoke(env, "window", "--hidden").exit_code == 0
    assert launches.calls == [True]


def test_window_passes_its_exit_code_on(env: Env, launches: Launches) -> None:
    launches.code = 1
    assert invoke(env, "window").exit_code == 1


def test_window_refuses_a_second_instance(
    env: Env, launches: Launches, running_service: Any
) -> None:
    result = invoke(env, "window")
    assert result.exit_code == 1
    assert launches.calls == []


def test_the_old_tray_command_runs_the_window_hidden(env: Env, launches: Launches) -> None:
    assert invoke(env, "tray").exit_code == 0
    assert launches.calls == [True]


def test_the_old_tray_command_is_hidden_from_help(env: Env) -> None:
    output = invoke(env, "--help").output
    assert "window" in output
    assert not any(line.strip(" │").startswith("tray ") for line in output.splitlines())
