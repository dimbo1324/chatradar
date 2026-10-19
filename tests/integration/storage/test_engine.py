from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from chatradar.domain.models import SyncState
from chatradar.storage.db import engine as engine_module
from chatradar.storage.db.engine import alembic_config_path, create_engine, upgrade_to_head
from tests.integration.storage.helpers import CHAT, make_message

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

    from chatradar.storage.db.repositories import SqlRepository

pytestmark = pytest.mark.integration


async def _pragma(engine: AsyncEngine, name: str) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(f"PRAGMA {name}"))).scalar()


async def test_file_database_gets_every_pragma(engine: AsyncEngine) -> None:
    assert await _pragma(engine, "journal_mode") == "wal"
    assert await _pragma(engine, "foreign_keys") == 1
    assert await _pragma(engine, "busy_timeout") == 5000
    assert await _pragma(engine, "synchronous") == 1  # NORMAL


async def test_memory_database_skips_wal_but_keeps_the_rest() -> None:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert await _pragma(engine, "journal_mode") == "memory"
        assert await _pragma(engine, "foreign_keys") == 1
        assert await _pragma(engine, "busy_timeout") == 5000
    finally:
        await engine.dispose()


async def test_upgrade_creates_the_schema_and_is_repeatable(engine: AsyncEngine) -> None:
    await upgrade_to_head(engine)
    async with engine.connect() as conn:
        names = set((await conn.execute(text("SELECT name FROM sqlite_master"))).scalars())
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert {"chats", "sync_state", "messages", "threads", "threads_fts"} <= names
    assert version == "0002"


async def test_upgrade_works_with_a_space_and_percent_in_the_url(tmp_path: Path) -> None:
    folder = tmp_path / "with space 100%"
    url = f"sqlite+aiosqlite:///{(folder / 'x.db').as_posix().replace('%', '%25')}"
    engine = create_engine(url)
    try:
        await upgrade_to_head(engine)
    finally:
        await engine.dispose()
    assert (folder / "x.db").is_file()


def test_alembic_config_prefers_the_current_directory(tmp_path: Path) -> None:
    assert alembic_config_path() == engine_module._REPO_ROOT / "alembic.ini"  # pyright: ignore[reportPrivateUsage]
    (tmp_path / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (tmp_path / "migrations").mkdir()
    assert alembic_config_path() == tmp_path / "alembic.ini"


def test_alembic_config_missing_everywhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_module, "_REPO_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError, match=r"alembic\.ini"):
        alembic_config_path()


async def test_datetimes_round_trip_as_utc(repo: SqlRepository) -> None:
    plus3 = timezone(timedelta(hours=3))
    local = datetime(2026, 10, 1, 15, 30, 45, tzinfo=plus3)
    message = make_message(1).model_copy(update={"date": local, "edited_at": local})
    await repo.upsert_many([message], 1)
    await repo.set_sync_state(
        SyncState(source=CHAT.source, chat_id=CHAT.chat_id, last_id="1", last_sync_at=local)
    )

    stored = (await repo.get_many([message.key]))[message.key]
    state = await repo.get_sync_state(CHAT.source, CHAT.chat_id)

    expected = datetime(2026, 10, 1, 12, 30, 45, tzinfo=UTC)
    assert stored.date == expected
    assert stored.date.tzinfo == UTC
    assert stored.edited_at == expected
    assert state is not None
    assert state.last_sync_at is not None
    assert state.last_sync_at == expected
    assert state.last_sync_at.tzinfo == UTC
