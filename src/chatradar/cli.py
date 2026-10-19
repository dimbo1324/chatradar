"""CLI entry point. Commands are thin wrappers over `services/`; no logic lives here."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path  # noqa: TC003 — Typer reads annotations at runtime
from typing import TYPE_CHECKING, Annotated

import typer

from chatradar import __version__
from chatradar.cli_learning import learning_app
from chatradar.cli_lexicon import lexicon_app
from chatradar.config import Settings, get_settings
from chatradar.logs import configure_logging, get_logger
from chatradar.services.container import open_runtime

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from typing import Any

    from chatradar.services.worker import ConnectorFactory

app = typer.Typer(name="chatradar", no_args_is_help=True, help="ChatRadar — a radar for chats.")
telegram_app = typer.Typer(no_args_is_help=True, help="Telegram account.")
chats_app = typer.Typer(no_args_is_help=True, help="Tracked chats.")
import_app = typer.Typer(no_args_is_help=True, help="Import manual exports.")
app.add_typer(telegram_app, name="telegram")
app.add_typer(chats_app, name="chats")
app.add_typer(import_app, name="import")
app.add_typer(lexicon_app, name="lexicon")
# `eval` and `mine` live at the top level, next to `process` and `rebuild`.
app.registered_commands.extend(learning_app.registered_commands)

log = get_logger(__name__)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _require_telegram(settings: Settings) -> None:
    if not settings.telegram.is_configured:
        typer.secho(
            "Telegram is not configured: set CHATRADAR_TELEGRAM__API_ID and "
            "CHATRADAR_TELEGRAM__API_HASH in .env (see README).",
            fg="red",
            err=True,
        )
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
    from chatradar.connectors.telegram.client import login  # Telethon only when needed

    settings = get_settings()
    _require_telegram(settings)
    settings.ensure_dirs()
    handle = _run(login(settings))
    typer.echo(f"Logged in as {handle}.")


@chats_app.command("add")
def chats_add(chat: Annotated[str, typer.Argument(help="@username, t.me link or chat id")]) -> None:
    """Start tracking a chat the Telegram account can read."""
    from chatradar.connectors.telegram.client import TelegramConnector
    from chatradar.services.sync import add_chat

    settings = get_settings()
    _require_telegram(settings)

    async def go() -> str:
        async with open_runtime(settings) as rt, TelegramConnector(settings) as tg:
            info = await add_chat(tg, chat, rt.repo, catalog=rt.raw)
        return f"{info.title} ({info.chat_id})"

    typer.echo(f"Tracking {_run(go())}.")


@chats_app.command("list")
def chats_list() -> None:
    """Show known chats with message counts."""

    async def go() -> list[str]:
        async with open_runtime(get_settings()) as rt:
            summaries = await rt.read.chats()
        return [
            f"{s.chat.chat_id:>16}  {s.message_count:>7} msgs  {s.thread_count:>5} threads  "
            f"{s.chat.title}" + (f"  @{s.chat.username}" if s.chat.username else "")
            for s in summaries
        ]

    lines = _run(go())
    typer.echo("\n".join(lines) if lines else "No chats yet.")


@import_app.command("tg-export")
def import_tg_export(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="result.json")],
    username: Annotated[
        str | None, typer.Option(help="Public @username of the chat, for t.me links")
    ] = None,
    run_pipeline: Annotated[
        bool, typer.Option("--process/--no-process", help="Run the pipeline afterwards")
    ] = True,
) -> None:
    """Import a Telegram Desktop JSON export."""
    from chatradar.services.ingest import import_tg_export as do_import
    from chatradar.services.process import process

    async def go() -> str:
        async with open_runtime(get_settings()) as rt:
            report = await do_import(
                path,
                username=username,
                raw=rt.raw,
                chats=rt.repo,
                messages=rt.repo,
                catalog=rt.raw,
            )
            processed = await process(rt.stage_deps) if run_pipeline else {}
        r = report.result
        return (
            f"{len(report.chats)} chat(s), {report.records} records: {r.inserted} new, "
            f"{r.updated} updated, {r.unchanged} unchanged. Processed: {processed or 'skipped'}."
        )

    typer.echo(_run(go()))


@app.command()
def sync(
    chat: Annotated[list[str] | None, typer.Option(help="Only this chat id (repeatable)")] = None,
    recheck_days: Annotated[int | None, typer.Option(help="Refetch the last N days")] = None,
) -> None:
    """Fetch new messages of tracked chats into data/raw/, then process them."""
    from chatradar.connectors.telegram.client import TelegramConnector
    from chatradar.services.process import process
    from chatradar.services.sync import sync_chats

    settings = get_settings()
    _require_telegram(settings)

    async def go() -> str:
        async with open_runtime(settings) as rt:
            async with TelegramConnector(settings) as tg:
                report = await sync_chats(
                    tg,
                    raw=rt.raw,
                    chats=rt.repo,
                    messages=rt.repo,
                    chat_ids=chat,
                    pause_sec=settings.worker.pause_between_chats_sec,
                    batch_size=settings.worker.batch_size,
                    recheck_days=recheck_days,
                )
            processed = await process(rt.stage_deps)
        return f"{len(report.chats)} chat(s), {report.fetched} fetched. Processed: {processed}."

    typer.echo(_run(go()))


@app.command()
def process(
    stage: Annotated[str | None, typer.Option(help="Only this stage")] = None,
    reset_stage: Annotated[
        str | None, typer.Option(help="Reprocess this stage and every later one")
    ] = None,
) -> None:
    """Run pipeline stages over unprocessed messages."""
    from chatradar.pipeline.base import STAGE_ORDER
    from chatradar.services.process import process as do_process

    for name in (stage, reset_stage):
        if name is not None and name not in STAGE_ORDER:
            typer.secho(
                f"unknown stage {name!r}; known: {', '.join(STAGE_ORDER)}", fg="red", err=True
            )
            raise typer.Exit(code=2)

    async def go() -> dict[str, int]:
        async with open_runtime(get_settings()) as rt:
            return await do_process(rt.stage_deps, only=stage, reset=reset_stage)

    typer.echo(f"Processed: {_run(go())}")


@app.command()
def rebuild() -> None:
    """Rebuild the database from data/raw/ without calling any source."""
    from chatradar.services.rebuild import rebuild as do_rebuild

    async def go() -> str:
        async with open_runtime(get_settings()) as rt:
            report = await do_rebuild(
                raw=rt.raw,
                catalog=rt.raw,
                store=rt.repo,
                chats=rt.repo,
                messages=rt.repo,
                deps=rt.stage_deps,
            )
        return f"{report.result.inserted} messages re-mapped. Processed: {report.processed}."

    typer.echo(_run(go()))


@app.command()
def web(
    host: Annotated[str | None, typer.Option(help="Bind address")] = None,
    port: Annotated[int | None, typer.Option(help="Port")] = None,
) -> None:
    """Start the web panel (uvicorn)."""
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
    """Background loop: migrate, then sync → process → sleep. Without Telegram settings it
    only processes (useful for imported exports)."""
    from chatradar.services.worker import run_forever

    settings = get_settings()
    connect: ConnectorFactory | None = None
    if settings.telegram.is_configured:
        from chatradar.connectors.telegram.client import TelegramConnector

        def connect_telegram() -> TelegramConnector:
            return TelegramConnector(settings)

        connect = connect_telegram
    else:
        log.warning("worker.telegram_not_configured")

    async def go() -> None:
        async with open_runtime(settings) as rt:
            log.info("worker.start", data_dir=str(settings.data_dir))
            await run_forever(rt, connect)

    try:
        _run(go())
    except KeyboardInterrupt:
        log.info("worker.stop")


def run() -> None:
    """`chatradar` entry point: UTF-8 stdout/stderr even on cp1252 Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8")
    app()
