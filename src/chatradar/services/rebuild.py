"""Use case: recreate the derived database from `data/raw/` without calling any source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chatradar.logs import get_logger
from chatradar.services.ingest import reingest_all
from chatradar.services.process import process

if TYPE_CHECKING:
    from chatradar.domain.models import UpsertResult
    from chatradar.domain.ports import (
        ChatCatalog,
        ChatRepository,
        DerivedDataStore,
        MessageRepository,
        RawStore,
    )
    from chatradar.pipeline.base import StageDeps

log = get_logger(__name__)


@dataclass(frozen=True)
class RebuildReport:
    result: UpsertResult
    processed: dict[str, int]


async def rebuild(
    *,
    raw: RawStore,
    catalog: ChatCatalog,
    store: DerivedDataStore,
    chats: ChatRepository,
    messages: MessageRepository,
    deps: StageDeps,
    batch_size: int = 500,
) -> RebuildReport:
    """Chats and sync state survive (`last_id` still matches the raw data); messages,
    threads and the index are cleared, re-mapped from every raw record, and processed."""
    await store.clear_derived()
    result = await reingest_all(
        raw=raw, chats=chats, messages=messages, catalog=catalog, batch_size=batch_size
    )
    processed = await process(deps, batch_size=batch_size)
    log.info("rebuild.done", count=result.inserted, processed=processed)
    return RebuildReport(result=result, processed=processed)
