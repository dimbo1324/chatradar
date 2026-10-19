from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chatradar import __version__
from chatradar.cli import app

runner = CliRunner()
FIXTURE = Path(__file__).parents[1] / "fixtures" / "tg_export" / "supergroup_result.json"


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("telegram", "chats", "import", "sync", "process", "rebuild", "web", "worker"):
        assert command in result.stdout


@pytest.mark.parametrize("args", [["telegram", "login"], ["sync"], ["chats", "add", "@x"]])
def test_telegram_commands_require_configuration(args: list[str]) -> None:
    result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "not configured" in result.stderr


@pytest.mark.integration
def test_import_then_list_process_and_rebuild() -> None:
    imported = runner.invoke(app, ["import", "tg-export", str(FIXTURE), "--username", "demo"])
    assert imported.exit_code == 0, (imported.output, imported.stderr)
    assert "60 records" in imported.stdout

    listed = runner.invoke(app, ["chats", "list"])
    assert listed.exit_code == 0
    assert "@demo" in listed.stdout

    again = runner.invoke(app, ["process"])
    assert again.exit_code == 0
    assert "'noise': 0" in again.stdout

    rebuilt = runner.invoke(app, ["rebuild"])
    assert rebuilt.exit_code == 0, rebuilt.output
    assert "re-mapped" in rebuilt.stdout


def test_unknown_reset_stage_is_an_error() -> None:
    result = runner.invoke(app, ["process", "--reset-stage", "nope"])

    assert result.exit_code == 2
    assert "unknown stage" in result.stderr
