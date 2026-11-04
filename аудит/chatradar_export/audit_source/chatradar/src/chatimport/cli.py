"""CLI entry point. Commands are thin wrappers; logic lives in the service modules.

The commands live in `cli_chats`, `cli_service` and `cli_data`; importing them registers them
on `app`.
"""

from __future__ import annotations

import io
import os
import sys
from typing import Annotated

import typer

from chatimport import __version__, cli_chats, cli_data, cli_service
from chatimport.cli_support import app
from chatimport.cli_support import instance_lock as _instance_lock

__all__ = ["_instance_lock", "app", "cli_chats", "cli_data", "cli_service", "main", "run"]

ENCODING_ENV = "PYTHONIOENCODING"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    context: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Version."),
    ] = False,
    root: Annotated[
        str | None,
        typer.Option("--root", help="Output folder for this run (overrides config and env)."),
    ] = None,
) -> None:
    """Export Telegram chats to local JSONL files."""
    context.obj = root


def _use_utf8_streams() -> None:
    """UTF-8 stdout/stderr even on cp1252 consoles, so Rich help cannot crash; an explicit
    `PYTHONIOENCODING` (for example cp866 for a PowerShell 5.1 pipe) is the user's choice."""
    if os.environ.get(ENCODING_ENV):
        return
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def run() -> None:
    """`chatimport` entry point."""
    _use_utf8_streams()
    app()
