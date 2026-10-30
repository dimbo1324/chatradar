"""The Typer apps and the helpers every CLI command module shares."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, Any, Final, NoReturn

import typer
from rich.cells import cell_len

from chatimport.config import MIB, ConfigError
from chatimport.control import (
    AlreadyRunning,
    CommandResult,
    acquire_instance_lock,
    send_command,
    service_running,
)
from chatimport.library import LibraryError
from chatimport.paths import cloud_sync_warning, library_path
from chatimport.ports import ChatImportError
from chatimport.trim import ALLOWED_PERCENTS

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from chatimport.app import ServiceContext

TRIM_CHOICES: Final = ALLOWED_PERCENTS
MB: Final = MIB
EXIT_ERROR: Final = 1
EXIT_NOT_CONFIGURED: Final = 2

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


@contextmanager
def handled() -> Generator[None]:
    try:
        yield
    except (AlreadyRunning, ChatImportError, ConfigError, LibraryError, TimeoutError) as exc:
        fail(str(exc))
    except KeyboardInterrupt:
        typer.secho("interrupted", err=True)
        raise typer.Exit(EXIT_ERROR) from None


def fail(message: str, code: int = EXIT_ERROR) -> NoReturn:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def warn(message: str) -> None:
    typer.secho(f"warning: {message}", fg=typer.colors.YELLOW, err=True)


def warn_if_cloud_synced(root: Path) -> None:
    warning = cloud_sync_warning(root)
    if warning is not None:
        warn(warning)


def load(context: typer.Context) -> ServiceContext:
    from chatimport.app import load_context

    root: str | None = context.obj
    return load_context(root)


def require_telegram(ctx: ServiceContext) -> None:
    if not ctx.config.telegram.is_configured:
        fail(
            f"Telegram api_id and api_hash are not set; edit {ctx.paths.config_file}",
            EXIT_NOT_CONFIGURED,
        )


@contextmanager
def instance_lock(ctx: ServiceContext) -> Generator[None]:
    lock = acquire_instance_lock(ctx.paths.lock_file)
    try:
        yield
    finally:
        lock.release()


def running(ctx: ServiceContext) -> bool:
    return service_running(ctx.paths.lock_file)


def refuse_second_instance(ctx: ServiceContext) -> None:
    if running(ctx):
        raise AlreadyRunning("another ChatImport instance is already running")


def send(ctx: ServiceContext, command: str, args: dict[str, Any] | None = None) -> CommandResult:
    result = send_command(ctx.paths.control_dir, command, args)
    if not result.ok:
        fail(result.message or f"{command} failed")
    return result


def confirm(question: str, yes: bool) -> None:
    if not yes and not typer.confirm(question, default=False):
        fail("aborted")


def need_service(ctx: ServiceContext, what: str) -> None:
    if not running(ctx):
        fail(f"{what} needs the service: start it with `chatimport tray` or `chatimport run`")


def library_file(ctx: ServiceContext) -> Path:
    return library_path(ctx.config.library.file, ctx.paths)


def table(rows: list[tuple[str, ...]]) -> None:
    """Columns padded by terminal cells, so emoji, wide letters and combining accents in titles
    do not shift the columns after them."""
    widths = [max(cell_len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        cells = (
            cell + " " * (width - cell_len(cell)) for cell, width in zip(row, widths, strict=True)
        )
        typer.echo("  ".join(cells).rstrip())
