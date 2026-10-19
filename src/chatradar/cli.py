"""Точка входа CLI. Команды — тонкие обёртки над функциями из `services/`, логики здесь нет."""

from __future__ import annotations

import io
import sys
from pathlib import Path  # noqa: TC003 — Typer читает аннотации в рантайме
from typing import Annotated

import typer

from chatradar import __version__
from chatradar.config import get_settings
from chatradar.logs import configure_logging, get_logger

app = typer.Typer(name="chatradar", no_args_is_help=True, help="ЧатРадар — радар по чатам.")
telegram_app = typer.Typer(no_args_is_help=True, help="Работа с аккаунтом Telegram.")
chats_app = typer.Typer(no_args_is_help=True, help="Список отслеживаемых чатов.")
import_app = typer.Typer(no_args_is_help=True, help="Импорт ручных выгрузок.")
app.add_typer(telegram_app, name="telegram")
app.add_typer(chats_app, name="chats")
app.add_typer(import_app, name="import")

log = get_logger(__name__)


def _not_implemented(step: int) -> None:
    typer.secho(f"Ещё не реализовано (шаг {step} плана, см. docs/architecture.md).", fg="yellow")
    raise typer.Exit(code=2)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Версия."),
    ] = False,
) -> None:
    settings = get_settings()
    configure_logging(settings.env, settings.log_level)


@telegram_app.command("login")
def telegram_login() -> None:
    """Первый вход в Telegram (интерактивно). Сессия сохраняется в data/sessions/."""
    _not_implemented(7)


@chats_app.command("add")
def chats_add(chat: Annotated[str, typer.Argument(help="@username или ID чата")]) -> None:
    """Добавить чат в список отслеживаемых."""
    _not_implemented(7)


@chats_app.command("list")
def chats_list() -> None:
    """Показать отслеживаемые чаты."""
    _not_implemented(3)


@import_app.command("tg-export")
def import_tg_export(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="result.json")],
) -> None:
    """Импорт JSON-выгрузки Telegram Desktop."""
    _not_implemented(2)


@app.command()
def sync(
    chat: Annotated[str | None, typer.Option(help="Только этот чат")] = None,
    recheck_days: Annotated[int | None, typer.Option(help="Перекачать последние N дней")] = None,
) -> None:
    """Докачать новые сообщения в data/raw/."""
    _not_implemented(7)


@app.command()
def process(
    stage: Annotated[str | None, typer.Option(help="Только эта стадия")] = None,
    reset_stage: Annotated[str | None, typer.Option(help="Сбросить версию стадии")] = None,
) -> None:
    """Прогнать стадии пайплайна над необработанными сообщениями."""
    _not_implemented(4)


@app.command()
def rebuild() -> None:
    """Пересобрать базу с нуля из data/raw/ без обращения к источникам."""
    _not_implemented(3)


@app.command()
def web(
    host: Annotated[str | None, typer.Option(help="Адрес")] = None,
    port: Annotated[int | None, typer.Option(help="Порт")] = None,
) -> None:
    """Запустить веб-панель (uvicorn)."""
    import uvicorn  # тяжёлый импорт только для этой команды

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
    """Фоновый цикл: sync → process → пауза."""
    settings = get_settings()
    settings.ensure_dirs()
    log.info("worker.start", data_dir=str(settings.data_dir))
    _not_implemented(7)


def run() -> None:
    """Точка входа `chatradar`: UTF-8 в stdout/stderr даже на Windows-консолях с cp1252."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8")
    app()
