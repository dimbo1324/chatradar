"""Composition root: builds the adapters from `Settings` and hands them to the use cases.

The only module that knows every concrete adapter. CLI, worker and web get a `Runtime`
(or `ReadServices`) from here and never construct storage themselves.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chatradar.pipeline.base import StageDeps
from chatradar.pipeline.registry import stage_versions
from chatradar.services.evaluation import evaluate_labels
from chatradar.services.feedback import FeedbackServices
from chatradar.services.lexicon_seed import ensure_seeded
from chatradar.services.queries import ReadServices
from chatradar.storage.db.engine import create_engine, upgrade_to_head
from chatradar.storage.db.lexicon_repo import SqlLabelRepository, SqlLexiconRepository
from chatradar.storage.db.repositories import SqlRepository
from chatradar.storage.db.search_fts5 import Fts5SearchIndex
from chatradar.storage.raw_jsonl import JsonlRawStore

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from chatradar.config import Settings
    from chatradar.domain.evaluation import EvalReport


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    engine: AsyncEngine
    repo: SqlRepository  # ChatRepository + MessageRepository + QueryRepository + MessageScanner
    search: Fts5SearchIndex
    raw: JsonlRawStore  # RawStore + ChatCatalog
    lexicon: SqlLexiconRepository
    labels: SqlLabelRepository

    @property
    def stage_deps(self) -> StageDeps:
        return StageDeps(messages=self.repo, search=self.search, lexicon=self.lexicon)

    @property
    def feedback(self) -> FeedbackServices:
        return FeedbackServices(lexicon=self.lexicon, labels=self.labels, messages=self.repo)

    @property
    def read(self) -> ReadServices:
        return ReadServices(
            queries=self.repo,
            search_index=self.search,
            stage_versions=stage_versions(),
            lexicon=self.lexicon,
            labels=self.labels,
            message_store=self.repo,
            quality_report=self._quality_report,
        )

    async def _quality_report(self) -> EvalReport:
        return await evaluate_labels(
            self.labels,
            self.repo,
            stage_versions=dict(stage_versions()),
            lexicon_revision=await self.lexicon.revision(),
        )


@asynccontextmanager
async def open_runtime(settings: Settings, *, migrate: bool = True) -> AsyncGenerator[Runtime]:
    """Create the data directories and the engine, apply migrations, seed the lexicon,
    dispose on exit."""
    settings.ensure_dirs()
    engine = create_engine(settings.database_url)
    try:
        if migrate:
            await upgrade_to_head(engine)
        runtime = Runtime(
            settings=settings,
            engine=engine,
            repo=SqlRepository(engine),
            search=Fts5SearchIndex(engine),
            raw=JsonlRawStore(settings.raw_dir),
            lexicon=SqlLexiconRepository(engine),
            labels=SqlLabelRepository(engine),
        )
        if migrate:
            await ensure_seeded(runtime.lexicon)
        yield runtime
    finally:
        await engine.dispose()


@asynccontextmanager
async def build_read_services(settings: Settings) -> AsyncGenerator[ReadServices]:
    """For the web app's lifespan. Migrating is idempotent, so the panel also works on a
    database the worker has not created yet."""
    async with open_runtime(settings) as runtime:
        yield runtime.read
