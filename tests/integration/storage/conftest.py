from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatradar.storage.db.engine import create_engine, upgrade_to_head
from chatradar.storage.db.repositories import SqlRepository
from chatradar.storage.db.search_fts5 import Fts5SearchIndex

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db' / 'test.db').as_posix()}")
    await upgrade_to_head(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def repo(engine: AsyncEngine) -> SqlRepository:
    return SqlRepository(engine)


@pytest.fixture
def index(engine: AsyncEngine) -> Fts5SearchIndex:
    return Fts5SearchIndex(engine)
