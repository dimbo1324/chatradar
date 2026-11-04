"""CLI commands for the account and the chat library: login, dialogs and `chats`."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

import typer

from chatimport.cli_support import (
    app,
    chats_app,
    handled,
    instance_lock,
    library_file,
    load,
    require_telegram,
    table,
)
from chatimport.library import Library, add_entry, load_library, set_enabled
from chatimport.ports import ResolveStatus
from chatimport.runtime import SystemClock
from chatimport.storage.layout import find_chat_folder
from chatimport.storage.state import StateUnreadable, load_state

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from chatimport.library import ChatEntry
    from chatimport.ports import ResolvedChat

log = logging.getLogger(__name__)

LIBRARY_HEADER = ("NAME", "REF", "STATUS", "CHAT_ID", "TITLE", "RECORDS")


def records_on_disk(root: Path, chat_id: int) -> int | None:
    """Stored records of one chat; None when nothing is stored or the state cannot be read."""
    folder = find_chat_folder(root, chat_id)
    if folder is None:
        return None
    try:
        state = load_state(folder)
    except StateUnreadable:
        log.warning("state.json is unreadable right now", extra={"chat_id": chat_id})
        return None
    return None if state is None else state.total_records


def library_rows(
    library: Library,
    resolved: Sequence[tuple[ChatEntry, ResolvedChat]],
    records_of: Callable[[int], int | None],
) -> list[tuple[str, ...]]:
    """One row per library entry; entries that were not resolved are shown as disabled."""
    rows: list[tuple[str, ...]] = []
    for entry, chat in resolved:
        status = chat.status.value if entry.enabled else "disabled"
        found = chat.status is ResolveStatus.FOUND and chat.chat_id is not None
        records = records_of(chat.chat_id) if found and chat.chat_id else None
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
    listed = {entry.key for entry, _ in resolved}
    rows.extend(
        (entry.name or entry.ref, entry.ref, "disabled", "", "", "")
        for entry in library.entries
        if entry.key not in listed
    )
    return rows


@app.command()
def login(context: typer.Context) -> None:
    """First login: phone, code and 2FA password; creates the session."""
    from chatimport.telegram.client import login as telegram_login

    with handled():
        ctx = load(context)
        require_telegram(ctx)
        with instance_lock(ctx):
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

    with handled():
        ctx = load(context)
        require_telegram(ctx)
        with instance_lock(ctx):
            rows = asyncio.run(collect())
        table([("CHAT_ID", "KIND", "TITLE", "LINK"), *rows])


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
        return library_rows(library, resolved, lambda chat_id: records_on_disk(ctx.root, chat_id))

    with handled():
        ctx = load(context)
        library = load_library(library_file(ctx))
        if not library.entries:
            typer.echo("The library is empty; add a chat with `chatimport chats add`.")
            return
        require_telegram(ctx)
        with instance_lock(ctx):
            rows = asyncio.run(resolve())
        table([LIBRARY_HEADER, *rows])


@chats_app.command("add")
def chats_add(
    context: typer.Context,
    ref: Annotated[str, typer.Argument(help="@username, link, numeric id or exact title.")],
    name: Annotated[str | None, typer.Option("--name", help="Short name for the entry.")] = None,
) -> None:
    """Add a chat to the library."""
    with handled():
        ctx = load(context)
        add_entry(library_file(ctx), ref, name)
        typer.echo(f"Added {ref}")


@chats_app.command("disable")
def chats_disable(
    context: typer.Context,
    target: Annotated[str, typer.Argument(help="Entry name or ref.")],
) -> None:
    """Stop collecting a chat; its data stays."""
    with handled():
        set_enabled(library_file(load(context)), target, False)
        typer.echo(f"Disabled {target}")


@chats_app.command("enable")
def chats_enable(
    context: typer.Context,
    target: Annotated[str, typer.Argument(help="Entry name or ref.")],
) -> None:
    """Resume collecting a disabled chat."""
    with handled():
        set_enabled(library_file(load(context)), target, True)
        typer.echo(f"Enabled {target}")
