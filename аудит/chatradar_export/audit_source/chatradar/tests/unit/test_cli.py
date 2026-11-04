from __future__ import annotations

from typer.testing import CliRunner

from chatimport import __version__
from chatimport.cli import app

runner = CliRunner()


def test_version_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "chatimport" in result.output.lower()
