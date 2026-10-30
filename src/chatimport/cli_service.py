"""CLI commands that run or steer the service: run, tray, status, pause, resume, recheck."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from chatimport.cli_support import (
    ChatOption,
    app,
    fail,
    handled,
    load,
    need_service,
    refuse_second_instance,
    require_telegram,
    running,
    send,
    warn_if_cloud_synced,
)
from chatimport.logging_setup import configure_logging
from chatimport.status import STATUS_FILE, format_chat_lines, format_status_lines, read_snapshot


@app.command("run")
def run_service(
    context: typer.Context,
    once: Annotated[bool, typer.Option("--once", help="Backfill or catch up, then exit.")] = False,
    chat: ChatOption = None,
) -> None:
    """Run the service in this console."""
    from chatimport.app import ChatImportApp
    from chatimport.runtime import LogNotifier

    with handled():
        ctx = load(context)
        require_telegram(ctx)
        refuse_second_instance(ctx)
        configure_logging(ctx.paths.log_dir, console=True)
        warn_if_cloud_synced(ctx.root)
        service = ChatImportApp(ctx, notifier=LogNotifier())
        if once:
            asyncio.run(service.run_once(chat))
        else:
            asyncio.run(service.run())


@app.command()
def tray(context: typer.Context) -> None:
    """Run the service with a tray icon (normal mode)."""
    from chatimport.tray import run_tray

    with handled():
        ctx = load(context)
        require_telegram(ctx)
        refuse_second_instance(ctx)
        run_tray(ctx)


@app.command()
def status(context: typer.Context) -> None:
    """Show the service status."""
    with handled():
        ctx = load(context)
        warn_if_cloud_synced(ctx.root)
        if running(ctx):
            data = send(ctx, "status").data
        else:
            if not (ctx.root / STATUS_FILE).is_file():
                fail("the service is not running and there is no status snapshot yet")
            snapshot = read_snapshot(ctx.root)
            if snapshot is None:
                fail(f"the status snapshot {ctx.root / STATUS_FILE} is unreadable")
            data = {**snapshot, "service": "stopped"}
            typer.echo(f"The service is not running (last snapshot {data.get('updated_at')}).")
        for line in [*format_status_lines(data), *format_chat_lines(data)]:
            typer.echo(line)


@app.command()
def pause(context: typer.Context, chat: ChatOption = None) -> None:
    """Stop collecting (all chats or one)."""
    with handled():
        ctx = load(context)
        need_service(ctx, "pause")
        typer.echo(send(ctx, "pause", {"chat": chat}).message or "Paused")


@app.command()
def resume(context: typer.Context, chat: ChatOption = None) -> None:
    """Continue collecting (all chats or one)."""
    with handled():
        ctx = load(context)
        need_service(ctx, "resume")
        typer.echo(send(ctx, "resume", {"chat": chat}).message or "Resumed")


@app.command()
def recheck(
    context: typer.Context,
    chat: ChatOption = None,
    days: Annotated[int | None, typer.Option("--days", min=1, help="Days to compare.")] = None,
) -> None:
    """Compare recent days with Telegram now and fix differences."""
    with handled():
        ctx = load(context)
        need_service(ctx, "recheck")
        result = send(ctx, "recheck", {"chat": chat, "days": days})
        typer.echo(result.message or "Recheck scheduled")
