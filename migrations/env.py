"""Alembic env: async engine, URL from Settings, batch mode on SQLite (ALTER needs it).

Programmatic use (tests, `chatradar worker`): pass a sync connection in
`config.attributes["connection"]`, or a URL in `config.attributes["url"]`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING, Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from chatradar.config import get_settings
from chatradar.storage.db.tables import FTS_TABLES, metadata

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url: str = config.attributes.get("url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", url)
target_metadata = metadata


def _is_sqlite() -> bool:
    return url.startswith("sqlite")


def _include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    return not (type_ == "table" and name is not None and name.startswith(FTS_TABLES))


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(),
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=_is_sqlite(),
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    if _is_sqlite():
        get_settings().ensure_dirs()
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (connection := config.attributes.get("connection")) is not None:
    _do_run_migrations(connection)
else:
    asyncio.run(run_migrations_online())
