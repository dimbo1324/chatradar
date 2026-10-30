"""CLI commands over the stored data: trim, backfill --deeper, check, export-json, set-root."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - Typer reads annotations at runtime
from typing import TYPE_CHECKING, Annotated

import typer

from chatimport.cli_support import (
    EXIT_ERROR,
    EXIT_NOT_CONFIGURED,
    MB,
    TRIM_CHOICES,
    ChatOption,
    YesOption,
    app,
    confirm,
    fail,
    handled,
    instance_lock,
    load,
    running,
    send,
    warn,
)
from chatimport.paths import normalize_root
from chatimport.storage.layout import find_chat_folder

if TYPE_CHECKING:
    from chatimport.trim import TrimReport


def _check_pct(value: int) -> int:
    if value not in TRIM_CHOICES:
        raise typer.BadParameter(f"must be one of {', '.join(map(str, TRIM_CHOICES))}")
    return value


def _echo_trim(report: TrimReport) -> None:
    typer.echo(
        f"Deleted {len(report.deleted_parts)} parts, {report.trimmed_records} records, "
        f"freed {report.freed_bytes / MB:.1f} MB"
    )


@app.command()
def trim(
    context: typer.Context,
    pct: Annotated[
        int, typer.Argument(callback=_check_pct, help="Share of the oldest history: 25, 50 or 75.")
    ],
    chat: ChatOption = None,
    yes: YesOption = False,
) -> None:
    """Delete the oldest share of the stored history."""
    from chatimport.offline import offline_trim, resolve_chat_selector

    with handled():
        ctx = load(context)
        scope = chat or "every chat"
        confirm(f"Delete the oldest {pct}% of the history of {scope}? This cannot be undone", yes)
        if running(ctx):
            result = send(ctx, "trim", {"pct": pct, "chat": chat})
            typer.echo(result.message or "Trim done")
            return
        with instance_lock(ctx):
            chat_id = None if chat is None else resolve_chat_selector(ctx, chat)
            _echo_trim(asyncio.run(offline_trim(ctx, pct, chat_id)))


@app.command()
def backfill(
    context: typer.Context,
    deeper: Annotated[
        bool, typer.Option("--deeper", help="Lower the history floor and fetch older messages.")
    ] = False,
    chat: ChatOption = None,
) -> None:
    """Fetch older history than the current floor."""
    from chatimport.offline import lower_floor, resolve_chat_selector

    with handled():
        if not deeper:
            fail("nothing to do: pass --deeper", EXIT_NOT_CONFIGURED)
        ctx = load(context)
        if running(ctx):
            typer.echo(send(ctx, "deeper", {"chat": chat}).message or "Deeper backfill started")
            return
        with instance_lock(ctx):
            chat_id = None if chat is None else resolve_chat_selector(ctx, chat)
            lowered = lower_floor(ctx.root, chat_id)
        typer.echo(
            f"Lowered the floor of {len(lowered)} chat(s); "
            "the next run will fetch the older history."
        )


@app.command()
def check(
    context: typer.Context,
    repair: Annotated[bool, typer.Option("--repair", help="Fix what can be fixed.")] = False,
) -> None:
    """Check the integrity of the stored files and state.json."""
    from chatimport.integrity import check_root

    with handled():
        ctx = load(context)
        if running(ctx):
            typer.echo(send(ctx, "check", {"repair": repair}).message or "Check done")
            return
        with instance_lock(ctx):
            issues = check_root(ctx.root, repair=repair, now=datetime.now(UTC))
        for issue in issues:
            where = issue.folder if issue.chat_id is None else f"{issue.chat_id} {issue.folder}"
            typer.echo(f"[{issue.severity}] {where}: {issue.message}")
        if not issues:
            typer.echo("No problems found")
        if any(issue.severity == "error" for issue in issues):
            raise typer.Exit(EXIT_ERROR)


@app.command("export-json")
def export_json(
    context: typer.Context,
    chat: Annotated[str, typer.Option("--chat", help="Chat name, @username, link or id.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output file (default: _exports/<chat folder>.json)."),
    ] = None,
    names: Annotated[
        bool,
        typer.Option(
            "--names/--no-names",
            help="Keep sender names (personal data); left out by default.",
        ),
    ] = False,
) -> None:
    """Assemble a classic JSON array from the stored parts of one chat."""
    from chatimport.export import export_chat_json
    from chatimport.offline import resolve_chat_selector

    with handled():
        ctx = load(context)
        chat_id = resolve_chat_selector(ctx, chat)
        folder = find_chat_folder(ctx.root, chat_id)
        if folder is None:
            fail(f"no stored data for chat {chat_id}")
        typer.echo(f"Wrote {export_chat_json(folder, out, include_names=names)}")


@app.command("set-root")
def set_root(
    context: typer.Context,
    path: Annotated[str, typer.Argument(help="New output folder.")],
    move: Annotated[bool, typer.Option("--move", help="Move the existing data there.")] = False,
    yes: YesOption = False,
) -> None:
    """Change the output folder."""
    from chatimport.config_edit import set_output_root
    from chatimport.setroot import move_root, validate_new_root

    with handled():
        ctx = load(context)
        new = normalize_root(path)
        for warning in validate_new_root(new, ctx.root, app_base=ctx.paths.base, move=move):
            warn(warning)
        if not move:
            confirm(
                f"Without --move the data in {ctx.root} stays there and chats are refetched "
                f"into {new}. Continue",
                yes,
            )
        if running(ctx):
            result = send(ctx, "set_root", {"path": str(new), "move": move})
            typer.echo(result.message or f"Output folder is now {new}")
            return
        with instance_lock(ctx):
            if move:
                asyncio.run(move_root(ctx.root, new, move=True))
            set_output_root(ctx.paths.config_file, new)
        typer.echo(f"Output folder is now {new}")
