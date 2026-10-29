"""CLI entry point. Commands are thin wrappers; logic lives in the service modules."""

from __future__ import annotations

import asyncio
import io
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 - Typer reads annotations at runtime
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import typer

from chatimport import __version__
from chatimport.config import ConfigError
from chatimport.control import (
    AlreadyRunning,
    CommandResult,
    acquire_instance_lock,
    send_command,
    service_running,
)
from chatimport.library import (
    LibraryError,
    add_entry,
    load_library,
    set_enabled,
)
from chatimport.paths import library_path, normalize_root
from chatimport.ports import ChatImportError, ResolveStatus
from chatimport.runtime import SystemClock
from chatimport.status import STATUS_FILE, format_status_lines
from chatimport.storage.layout import find_chat_folder
from chatimport.storage.state import load_state

if TYPE_CHECKING:
    from collections.abc import Generator

    from chatimport.app import ServiceContext
    from chatimport.trim import TrimReport

TRIM_CHOICES = (25, 50, 75)
MB = 1024 * 1024
EXIT_ERROR = 1
EXIT_NOT_CONFIGURED = 2

app = typer.Typer(
    name="chatimport",
    no_args_is_help=True,
    help="ChatImport — local export of Telegram chats to JSONL.",
)
chats_app = typer.Typer(no_args_is_help=True, help="Manage the chat library.")
app.add_typer(chats_app, name="chats")

ChatOption = Annotated[
    str | None,
    typer.Option("--chat", help="Chat name, @username, link or numeric id."),
]
YesOption = Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")]


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


@contextmanager
def _handled() -> Generator[None]:
    try:
        yield
    except (AlreadyRunning, ChatImportError, ConfigError, LibraryError) as exc:
        _fail(str(exc))
    except TimeoutError as exc:
        _fail(str(exc))
    except KeyboardInterrupt:
        typer.secho("interrupted", err=True)
        raise typer.Exit(EXIT_ERROR) from None


def _fail(message: str, code: int = EXIT_ERROR) -> NoReturn:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _load(context: typer.Context) -> ServiceContext:
    from chatimport.app import load_context

    root: str | None = context.obj
    return load_context(root)


def _require_telegram(ctx: ServiceContext) -> None:
    if not ctx.config.telegram.is_configured:
        _fail(
            f"Telegram api_id and api_hash are not set; edit {ctx.paths.config_file}",
            EXIT_NOT_CONFIGURED,
        )


@contextmanager
def _instance_lock(ctx: ServiceContext) -> Generator[None]:
    lock = acquire_instance_lock(ctx.paths.lock_file)
    try:
        yield
    finally:
        lock.release()


def _running(ctx: ServiceContext) -> bool:
    return service_running(ctx.paths.lock_file)


def _send(ctx: ServiceContext, command: str, args: dict[str, Any] | None = None) -> CommandResult:
    result = send_command(ctx.paths.control_dir, command, args)
    if not result.ok:
        _fail(result.message or f"{command} failed")
    return result


def _confirm(question: str, yes: bool) -> None:
    if not yes and not typer.confirm(question, default=False):
        _fail("aborted")


def _need_service(ctx: ServiceContext, what: str) -> None:
    if not _running(ctx):
        _fail(f"{what} needs the service: start it with `chatimport tray` or `chatimport run`")


def _library_file(ctx: ServiceContext) -> Path:
    return library_path(ctx.config.library.file, ctx.paths)


def _records_on_disk(ctx: ServiceContext, chat_id: int) -> int | None:
    folder = find_chat_folder(ctx.root, chat_id)
    state = load_state(folder) if folder is not None else None
    return None if state is None else sum(chunk.records for chunk in state.chunks.values())


def _table(rows: list[tuple[str, ...]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        )


@app.command()
def login(context: typer.Context) -> None:
    """First login: phone, code and 2FA password; creates the session."""
    from chatimport.telegram.client import login as telegram_login

    with _handled():
        ctx = _load(context)
        _require_telegram(ctx)
        with _instance_lock(ctx):
            handle = asyncio.run(
                telegram_login(
                    ctx.config.telegram,
                    ctx.paths.session_file,
                    prompt_phone=lambda: typer.prompt("Phone number (international format)"),
                    prompt_code=lambda: typer.prompt("Login code"),
                    prompt_password=lambda: typer.prompt("2FA password", hide_input=True),
                )
            )
        typer.echo(f"Logged in as {handle}")


@app.command()
def dialogs(context: typer.Context) -> None:
    """List the groups and channels of the account."""
    from chatimport.app import build_gateway

    async def collect() -> list[tuple[str, ...]]:
        gateway = build_gateway(ctx, SystemClock())
        await gateway.connect()
        try:
            found = await gateway.list_dialogs()
        finally:
            await gateway.disconnect()
        return [(str(d.chat_id), d.kind, d.title, d.link or "") for d in found]

    with _handled():
        ctx = _load(context)
        _require_telegram(ctx)
        with _instance_lock(ctx):
            rows = asyncio.run(collect())
        _table([("CHAT_ID", "KIND", "TITLE", "LINK"), *rows])


@chats_app.command("list")
def chats_list(context: typer.Context) -> None:
    """Show every library entry with its resolved chat and stored record count."""
    from chatimport.app import build_gateway, resolve_library

    async def resolve() -> list[tuple[str, ...]]:
        gateway = build_gateway(ctx, SystemClock())
        await gateway.connect()
        try:
            resolved = await resolve_library(gateway, library)
        finally:
            await gateway.disconnect()
        rows: list[tuple[str, ...]] = []
        for entry, chat in resolved:
            status = chat.status.value if entry.enabled else "disabled"
            found = chat.status is ResolveStatus.FOUND and chat.chat_id is not None
            records = _records_on_disk(ctx, chat.chat_id) if found and chat.chat_id else None
            rows.append(
                (
                    entry.name or entry.ref,
                    entry.ref,
                    status,
                    "" if chat.chat_id is None else str(chat.chat_id),
                    chat.title or "",
                    "" if records is None else str(records),
                )
            )
        return rows

    with _handled():
        ctx = _load(context)
        library = load_library(_library_file(ctx))
        if not library.entries:
            typer.echo("The library is empty; add a chat with `chatimport chats add`.")
            return
        _require_telegram(ctx)
        with _instance_lock(ctx):
            rows = asyncio.run(resolve())
        _table([("NAME", "REF", "STATUS", "CHAT_ID", "TITLE", "RECORDS"), *rows])


@chats_app.command("add")
def chats_add(
    context: typer.Context,
    ref: Annotated[str, typer.Argument(help="@username, link, numeric id or exact title.")],
    name: Annotated[str | None, typer.Option("--name", help="Short name for the entry.")] = None,
) -> None:
    """Add a chat to the library."""
    with _handled():
        ctx = _load(context)
        add_entry(_library_file(ctx), ref, name)
        typer.echo(f"Added {ref}")


@chats_app.command("disable")
def chats_disable(
    context: typer.Context,
    target: Annotated[str, typer.Argument(help="Entry name or ref.")],
) -> None:
    """Stop collecting a chat; its data stays."""
    with _handled():
        set_enabled(_library_file(_load(context)), target, False)
        typer.echo(f"Disabled {target}")


@chats_app.command("enable")
def chats_enable(
    context: typer.Context,
    target: Annotated[str, typer.Argument(help="Entry name or ref.")],
) -> None:
    """Resume collecting a disabled chat."""
    with _handled():
        set_enabled(_library_file(_load(context)), target, True)
        typer.echo(f"Enabled {target}")


@app.command("run")
def run_service(
    context: typer.Context,
    once: Annotated[bool, typer.Option("--once", help="Backfill or catch up, then exit.")] = False,
    chat: ChatOption = None,
) -> None:
    """Run the service in this console."""
    from chatimport.app import ChatImportApp
    from chatimport.runtime import LogNotifier

    with _handled():
        ctx = _load(context)
        _require_telegram(ctx)
        if _running(ctx):
            raise AlreadyRunning("another ChatImport instance is already running")
        service = ChatImportApp(ctx, notifier=LogNotifier())
        if once:
            asyncio.run(service.run_once(chat))
        else:
            asyncio.run(service.run())


@app.command()
def tray(context: typer.Context) -> None:
    """Run the service with a tray icon (normal mode)."""
    from chatimport.tray import run_tray

    with _handled():
        ctx = _load(context)
        _require_telegram(ctx)
        if _running(ctx):
            raise AlreadyRunning("another ChatImport instance is already running")
        run_tray(ctx)


def _chat_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for chat in data.get("chats", []):
        extra = ", paused" if chat.get("paused") else ""
        done = "done" if chat.get("backfill_done") else "in progress"
        lines.append(
            f"  {chat.get('chat_id')} {chat.get('title', '')}: {chat.get('phase')}, "
            f"last_id {chat.get('last_id')}, backfill {done}, "
            f"{chat.get('records', 0)} records{extra}"
        )
    return lines


@app.command()
def status(context: typer.Context) -> None:
    """Show the service status."""
    with _handled():
        ctx = _load(context)
        if _running(ctx):
            data = _send(ctx, "status").data
        else:
            snapshot = ctx.root / STATUS_FILE
            if not snapshot.is_file():
                _fail("the service is not running and there is no status snapshot yet")
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            data["service"] = "stopped"
            typer.echo(f"The service is not running (last snapshot {data.get('updated_at')}).")
        for line in [*format_status_lines(data), *_chat_lines(data)]:
            typer.echo(line)


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

    with _handled():
        ctx = _load(context)
        scope = chat or "every chat"
        _confirm(f"Delete the oldest {pct}% of the history of {scope}? This cannot be undone", yes)
        if _running(ctx):
            result = _send(ctx, "trim", {"pct": pct, "chat": chat})
            typer.echo(result.message or "Trim done")
            return
        with _instance_lock(ctx):
            chat_id = None if chat is None else resolve_chat_selector(ctx, chat)
            _echo_trim(asyncio.run(offline_trim(ctx, pct, chat_id)))


@app.command()
def pause(context: typer.Context, chat: ChatOption = None) -> None:
    """Stop collecting (all chats or one)."""
    with _handled():
        ctx = _load(context)
        _need_service(ctx, "pause")
        typer.echo(_send(ctx, "pause", {"chat": chat}).message or "Paused")


@app.command()
def resume(context: typer.Context, chat: ChatOption = None) -> None:
    """Continue collecting (all chats or one)."""
    with _handled():
        ctx = _load(context)
        _need_service(ctx, "resume")
        typer.echo(_send(ctx, "resume", {"chat": chat}).message or "Resumed")


@app.command()
def recheck(
    context: typer.Context,
    chat: ChatOption = None,
    days: Annotated[int | None, typer.Option("--days", min=1, help="Days to compare.")] = None,
) -> None:
    """Compare recent days with Telegram now and fix differences."""
    with _handled():
        ctx = _load(context)
        _need_service(ctx, "recheck")
        result = _send(ctx, "recheck", {"chat": chat, "days": days})
        typer.echo(result.message or "Recheck scheduled")


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

    with _handled():
        if not deeper:
            _fail("nothing to do: pass --deeper", EXIT_NOT_CONFIGURED)
        ctx = _load(context)
        if _running(ctx):
            typer.echo(_send(ctx, "deeper", {"chat": chat}).message or "Deeper backfill started")
            return
        with _instance_lock(ctx):
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

    with _handled():
        ctx = _load(context)
        if _running(ctx):
            typer.echo(_send(ctx, "check", {"repair": repair}).message or "Check done")
            return
        with _instance_lock(ctx):
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
    out: Annotated[Path | None, typer.Option("--out", help="Output file.")] = None,
) -> None:
    """Assemble a classic JSON array from the stored parts of one chat."""
    from chatimport.export import export_chat_json
    from chatimport.offline import resolve_chat_selector

    with _handled():
        ctx = _load(context)
        chat_id = resolve_chat_selector(ctx, chat)
        folder = find_chat_folder(ctx.root, chat_id)
        if folder is None:
            _fail(f"no stored data for chat {chat_id}")
        typer.echo(f"Wrote {export_chat_json(folder, out)}")


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

    with _handled():
        ctx = _load(context)
        new = normalize_root(path)
        for warning in validate_new_root(new, ctx.root):
            typer.secho(f"warning: {warning}", fg=typer.colors.YELLOW, err=True)
        if not move:
            _confirm(
                f"Without --move the data in {ctx.root} stays there and chats are refetched "
                f"into {new}. Continue",
                yes,
            )
        if _running(ctx):
            result = _send(ctx, "set_root", {"path": str(new), "move": move})
            typer.echo(result.message or f"Output folder is now {new}")
            return
        with _instance_lock(ctx):
            if move:
                asyncio.run(move_root(ctx.root, new, move=True))
            set_output_root(ctx.paths.config_file, new)
        typer.echo(f"Output folder is now {new}")


def run() -> None:
    """`chatimport` entry point: UTF-8 stdout/stderr even on cp1252 Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8")
    app()
