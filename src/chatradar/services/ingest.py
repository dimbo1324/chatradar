"""Ingestion use cases: import a Telegram Desktop export, re-map all raw data (rebuild)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from chatradar.connectors.telegram.mapper import map_record as map_telethon
from chatradar.connectors.tg_export.mapper import map_record as map_tg_export
from chatradar.connectors.tg_export.parser import parse_export
from chatradar.domain.models import ChatInfo, RawKind, RawRecord, UpsertResult
from chatradar.logs import get_logger
from chatradar.services.normalize import normalize_records

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from chatradar.domain.ports import ChatRepository, Mapper, MessageRepository, RawStore

log = get_logger(__name__)

MAPPERS: dict[RawKind, Mapper] = {
    RawKind.TG_DESKTOP: map_tg_export,
    RawKind.TELETHON: map_telethon,
}


class ChatCatalog(Protocol):
    """Chat metadata kept beside the raw data (`JsonlRawStore` implements it).

    The database is derived from raw data, but `RawRecord` carries no chat title or
    username; without this a rebuild would lose titles and public links.
    """

    async def save_chats(self, chats: Sequence[ChatInfo]) -> None: ...
    async def load_chats(self) -> list[ChatInfo]: ...


@dataclass(frozen=True)
class ImportReport:
    chats: list[ChatInfo]
    records: int
    result: UpsertResult = field(default_factory=UpsertResult)


async def import_tg_export(
    path: Path,
    *,
    username: str | None = None,
    raw: RawStore,
    chats: ChatRepository,
    messages: MessageRepository,
    catalog: ChatCatalog | None = None,
) -> ImportReport:
    """Parse the export, register its chats, store the raw records, then normalize them.

    Importing the same file twice appends its records to the raw store again; the upsert
    makes that harmless for the database.
    """
    fetched_at = datetime.now(UTC)
    parsed = await asyncio.to_thread(parse_export, path, fetched_at=fetched_at, username=username)
    chat_infos = [chat for chat, _ in parsed]
    records = [record for _, chat_records in parsed for record in chat_records]
    await chats.upsert_chats(chat_infos)
    if catalog is not None:
        await catalog.save_chats(chat_infos)
    await raw.append(records)
    result = await normalize_records(records, mappers=MAPPERS, chats=chats, messages=messages)
    log.info("import.done", chats=len(chat_infos), count=len(records), inserted=result.inserted)
    return ImportReport(chats=chat_infos, records=len(records), result=result)


async def reingest_all(
    *,
    raw: RawStore,
    chats: ChatRepository,
    messages: MessageRepository,
    catalog: ChatCatalog | None = None,
    batch_size: int = 500,
) -> UpsertResult:
    """Map every stored raw record again — the core of `chatradar rebuild`. No source is
    called; chats saved in the catalog are registered first so links survive."""
    if catalog is not None:
        known = await catalog.load_chats()
        if known:
            await chats.upsert_chats(known)
    total = UpsertResult()
    batch: list[RawRecord] = []
    async for record in raw.read():
        batch.append(record)
        if len(batch) >= batch_size:
            total += await _normalize_latest(batch, chats=chats, messages=messages)
            batch = []
    if batch:
        total += await _normalize_latest(batch, chats=chats, messages=messages)
    return total


async def _normalize_latest(
    batch: Sequence[RawRecord], *, chats: ChatRepository, messages: MessageRepository
) -> UpsertResult:
    """One upsert per message: an edited message stored twice keeps its latest record."""
    latest: dict[tuple[str, str, str], RawRecord] = {}
    for record in batch:
        key = (record.source, record.chat_id, str(record.payload.get("id")))
        latest[key] = record
    return await normalize_records(
        list(latest.values()), mappers=MAPPERS, chats=chats, messages=messages
    )
