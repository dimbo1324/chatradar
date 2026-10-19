"""Порты — структурные интерфейсы (Protocol). Адаптерам не нужно наследоваться от них.

Типы `StoredMessage`, `StageResult`, `UpsertResult`, `SearchFilters`, `Hit` появятся
вместе с хранилищем (шаг 3 плана) и сейчас объявлены как заглушки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from chatradar.domain.models import ChatInfo, Message, RawRecord, Source

# TODO(шаг 3): заменить на настоящие модели.
type StoredMessage = Any
type StageResult = Any
type UpsertResult = Any
type Indexable = Any
type SearchFilters = Any
type Hit = Any


class Connector(Protocol):
    source: Source

    async def list_chats(self) -> list[ChatInfo]: ...
    def fetch(self, chat_id: str, since_id: str | None) -> AsyncIterator[RawRecord]: ...
    def message_link(self, chat: ChatInfo, msg_id: str) -> str | None: ...


class RawStore(Protocol):
    async def append(self, source: Source, chat_id: str, records: list[RawRecord]) -> None: ...
    def read(self, source: Source, chat_id: str) -> AsyncIterator[RawRecord]: ...


class MessageRepository(Protocol):
    async def upsert_many(self, msgs: list[Message]) -> UpsertResult: ...
    async def pending_for(self, stage: str, version: int, limit: int) -> list[StoredMessage]: ...
    async def mark(self, stage: str, version: int, updates: list[StageResult]) -> None: ...


class SearchIndex(Protocol):
    async def index(self, items: list[Indexable]) -> None: ...
    async def search(self, query: str, filters: SearchFilters) -> list[Hit]: ...
