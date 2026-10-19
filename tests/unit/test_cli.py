from __future__ import annotations

from typer.testing import CliRunner

from chatradar import __version__
from chatradar.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("telegram", "chats", "import", "sync", "process", "rebuild", "web", "worker"):
        assert command in result.stdout


def test_unimplemented_command_exits_with_code_2() -> None:
    result = runner.invoke(app, ["rebuild"])

    assert result.exit_code == 2
