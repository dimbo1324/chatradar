"""Sync use cases: track a chat, fetch new messages from the live connector.

Delivery is at-least-once: every batch is written to the raw store first, then the chat's
`last_id` advances, then the batch is normalized. A crash in between refetches a batch,
and the upsert makes the repeat harmless.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from chatradar.domain.models import ChatInfo, RawRecord, Source, SyncState, UpsertResult
from chatradar.logs import get_logger
from chatradar.services.ingest import MAPPERS
from chatradar.services.normalize import normalize_records

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Collection

    from chatradar.domain.ports import ChatRepository, MessageRepository, RawStore
    from chatradar.services.ingest import ChatCatalog

log = get_logger(__name__)


class LiveConnector(Protocol):
    """The `Connector` port plus what tracking and edit rechecks need (`TelegramConnector`)."""

    source: Source

    async def resolve(self, ref: str) -> ChatInfo: ...

    def fetch(self, chat: ChatInfo, since_id: str | None) -> AsyncIterator[RawRecord]: ...

    def fetch_recent(self, chat: ChatInfo, days: int) -> AsyncIterator[RawRecord]: ...


@dataclass(frozen=True)
class ChatSyncReport:
    chat_id: str
    fetched: int
    rechecked: int
    last_id: str | None


@dataclass(frozen=True)
class SyncReport:
    chats: list[ChatSyncReport]
    result: UpsertResult = field(default_factory=UpsertResult)

    @property
    def fetched(self) -> int:
        return sum(chat.fetched + chat.rechecked for chat in self.chats)


async def add_chat(
    connector: LiveConnector,
    ref: str,
    chats: ChatRepository,
    catalog: ChatCatalog | None = None,
) -> ChatInfo:
    """Resolve `@username`, a link or an id and start tracking that chat."""
    chat = await connector.resolve(ref)
    await chats.upsert_chats([chat])
    if catalog is not None:
        await catalog.save_chats([chat])
    log.info("sync.chat_added", chat_id=chat.chat_id, kind=chat.kind)
    return chat


async def sync_chats(
    connector: LiveConnector,
    *,
    raw: RawStore,
    chats: ChatRepository,
    messages: MessageRepository,
    chat_ids: Collection[str] | None = None,
    pause_sec: float,
    batch_size: int = 500,
    recheck_days: int | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SyncReport:
    """Fetch every tracked chat of the connector's source (or only `chat_ids`) since its
    `last_id`; with `recheck_days`, also refetch that many recent days to catch edits."""
    tracked = [
        chat
        for chat in await chats.list_chats()
        if chat.source is connector.source and (chat_ids is None or chat.chat_id in chat_ids)
    ]
    reports: list[ChatSyncReport] = []
    total = UpsertResult()
    for position, chat in enumerate(tracked):
        if position:
            await sleep(pause_sec)
        state = await chats.get_sync_state(chat.source, chat.chat_id)
        run = _ChatRun(chat, raw=raw, chats=chats, messages=messages)
        run.last_id = state.last_id if state else None
        fetched = await run.consume(connector.fetch(chat, run.last_id), batch_size)
        rechecked = 0
        if recheck_days:
            rechecked = await run.consume(connector.fetch_recent(chat, recheck_days), batch_size)
        await run.save_state()
        total += run.result
        reports.append(ChatSyncReport(chat.chat_id, fetched, rechecked, run.last_id))
        log.info(
            "sync.chat_done",
            stage="sync",
            chat_id=chat.chat_id,
            count=fetched,
            rechecked=rechecked,
            inserted=run.result.inserted,
            updated=run.result.updated,
        )
    return SyncReport(chats=reports, result=total)


class _ChatRun:
    def __init__(
        self,
        chat: ChatInfo,
        *,
        raw: RawStore,
        chats: ChatRepository,
        messages: MessageRepository,
    ) -> None:
        self.chat = chat
        self.raw = raw
        self.chats = chats
        self.messages = messages
        self.last_id: str | None = None
        self.result = UpsertResult()

    async def consume(self, records: AsyncIterator[RawRecord], batch_size: int) -> int:
        count = 0
        batch: list[RawRecord] = []
        async for record in records:
            batch.append(record)
            if len(batch) >= batch_size:
                count += await self._flush(batch)
                batch = []
        if batch:
            count += await self._flush(batch)
        return count

    async def _flush(self, batch: list[RawRecord]) -> int:
        await self.raw.append(batch)
        self.last_id = _max_id(self.last_id, batch)
        await self.save_state()
        self.result += await normalize_records(
            batch, mappers=MAPPERS, chats=self.chats, messages=self.messages
        )
        return len(batch)

    async def save_state(self) -> None:
        await self.chats.set_sync_state(
            SyncState(
                source=self.chat.source,
                chat_id=self.chat.chat_id,
                last_id=self.last_id,
                last_sync_at=datetime.now(UTC),
            )
        )


def _max_id(current: str | None, batch: list[RawRecord]) -> str | None:
    """The highest message id seen; never moves backwards."""
    ids = [value for record in batch if isinstance(value := record.payload.get("id"), int)]
    if current is not None and current.isdigit():
        ids.append(int(current))
    return str(max(ids)) if ids else current
