"""CLI entry point. Commands are thin wrappers over `services/`; no logic lives here."""

from __future__ import annotations

import io
import sys
from pathlib import Path  # noqa: TC003 — Typer reads annotations at runtime
from typing import Annotated

import typer

from chatradar import __version__
from chatradar.config import get_settings
from chatradar.logs import configure_logging, get_logger

app = typer.Typer(name="chatradar", no_args_is_help=True, help="ChatRadar — a radar for chats.")
telegram_app = typer.Typer(no_args_is_help=True, help="Telegram account.")
chats_app = typer.Typer(no_args_is_help=True, help="Tracked chats.")
import_app = typer.Typer(no_args_is_help=True, help="Import manual exports.")
app.add_typer(telegram_app, name="telegram")
app.add_typer(chats_app, name="chats")
app.add_typer(import_app, name="import")

log = get_logger(__name__)


def _not_implemented(step: int) -> None:
    typer.secho(f"Not implemented yet (step {step}, see docs/ROADMAP.md).", fg="yellow")
    raise typer.Exit(code=2)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Version."),
    ] = False,
) -> None:
    settings = get_settings()
    configure_logging(settings.env, settings.log_level)


@telegram_app.command("login")
def telegram_login() -> None:
    """First Telegram login (interactive). The session is stored in data/sessions/."""
    _not_implemented(7)


@chats_app.command("add")
def chats_add(chat: Annotated[str, typer.Argument(help="@username or chat id")]) -> None:
    """Add a chat to the tracked list."""
    _not_implemented(7)


@chats_app.command("list")
def chats_list() -> None:
    """Show tracked chats."""
    _not_implemented(3)


@import_app.command("tg-export")
def import_tg_export(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="result.json")],
) -> None:
    """Import a Telegram Desktop JSON export."""
    _not_implemented(2)


@app.command()
def sync(
    chat: Annotated[str | None, typer.Option(help="Only this chat")] = None,
    recheck_days: Annotated[int | None, typer.Option(help="Refetch the last N days")] = None,
) -> None:
    """Fetch new messages into data/raw/."""
    _not_implemented(7)


@app.command()
def process(
    stage: Annotated[str | None, typer.Option(help="Only this stage")] = None,
    reset_stage: Annotated[str | None, typer.Option(help="Reset this stage's version")] = None,
) -> None:
    """Run pipeline stages over unprocessed messages."""
    _not_implemented(4)


@app.command()
def rebuild() -> None:
    """Rebuild the database from data/raw/ without calling any source."""
    _not_implemented(3)


@app.command()
def web(
    host: Annotated[str | None, typer.Option(help="Bind address")] = None,
    port: Annotated[int | None, typer.Option(help="Port")] = None,
) -> None:
    """Start the debug web panel (uvicorn)."""
    import uvicorn  # heavy import, needed by this command only

    settings = get_settings()
    uvicorn.run(
        "chatradar.web.app:create_app",
        factory=True,
        host=host or settings.web.host,
        port=port or settings.web.port,
        log_level=settings.log_level.lower(),
    )


@app.command()
def worker() -> None:
    """Background loop: sync → process → sleep."""
    settings = get_settings()
    settings.ensure_dirs()
    log.info("worker.start", data_dir=str(settings.data_dir))
    _not_implemented(7)


def run() -> None:
    """`chatradar` entry point: UTF-8 stdout/stderr even on cp1252 Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8")
    app()
