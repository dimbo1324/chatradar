"""The async engine (SQLite pragmas on every connection) and programmatic migrations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.engine.interfaces import DBAPIConnection
    from sqlalchemy.ext.asyncio import AsyncEngine
    from sqlalchemy.pool import ConnectionPoolEntry

_REPO_ROOT = Path(__file__).resolve().parents[4]

SQLITE_PRAGMAS: tuple[str, ...] = (
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def create_engine(url: str) -> AsyncEngine:
    """An async engine; on SQLite every new connection gets WAL (files only) and the
    pragmas the worker and the web panel rely on, and the database directory exists."""
    engine = create_async_engine(url)
    if engine.dialect.name != "sqlite":
        return engine

    database = engine.url.database
    in_memory = database in (None, "", ":memory:") or engine.url.query.get("mode") == "memory"
    if not in_memory and database is not None:
        Path(database).parent.mkdir(parents=True, exist_ok=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_pragmas(  # pyright: ignore[reportUnusedFunction]
        dbapi_connection: DBAPIConnection, _record: ConnectionPoolEntry
    ) -> None:
        cursor = dbapi_connection.cursor()
        try:
            if not in_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            for pragma in SQLITE_PRAGMAS:
                cursor.execute(pragma)
        finally:
            cursor.close()

    return engine


def alembic_config_path() -> Path:
    """`alembic.ini` next to `migrations/`: the current directory first (the Docker image
    runs from `/app`), then the repository this package was loaded from."""
    for base in (Path.cwd(), _REPO_ROOT):
        ini = base / "alembic.ini"
        if ini.is_file() and (base / "migrations").is_dir():
            return ini
    raise FileNotFoundError("alembic.ini with a migrations/ folder not found")


async def upgrade_to_head(engine: AsyncEngine) -> None:
    """Apply every Alembic migration through this engine's own connection."""
    config = Config(str(alembic_config_path()))
    config.attributes["skip_logging"] = True
    # env.py feeds the URL to configparser, where a bare % starts an interpolation.
    config.attributes["url"] = engine.url.render_as_string(hide_password=True).replace("%", "%%")
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade, config)


def _upgrade(connection: Connection, config: Config) -> None:
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
