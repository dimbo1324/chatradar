"""The search contract: what the index returns and what the window asks for.

The index (`search_index`) and the desktop page both build on these types, so neither depends
on the other. Everything here is plain data; sender names are never part of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

MIN_INDEXED_LENGTH = 3
DEFAULT_PAGE_SIZE = 100


class IndexState(StrEnum):
    DISABLED = "disabled"
    BUILDING = "building"
    READY = "ready"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """`text` is what the person typed (matched as a case-, accent- and yo-insensitive
    substring). `chat_ids` of None means every chat; `since` is inclusive, `until` exclusive.
    """

    text: str
    chat_ids: frozenset[int] | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SearchHit:
    chat_id: int
    chat_title: str
    msg_id: int
    date: datetime
    text: str
    edited: bool
    link: str | None


@dataclass(frozen=True, slots=True)
class SearchPage:
    """`total` counts every match of the query (not only this page); newest first."""

    hits: tuple[SearchHit, ...]
    total: int
    query: SearchQuery


@dataclass(frozen=True, slots=True)
class ContextMessage:
    msg_id: int
    date: datetime
    text: str
    edited: bool
    is_target: bool


@dataclass(frozen=True, slots=True)
class IndexStatus:
    """`indexed` and `total` count messages; progress is `indexed / total` while building."""

    state: IndexState
    indexed: int
    total: int
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChatChoice:
    chat_id: int
    title: str
    messages: int


class SearchBackend(Protocol):
    """A read-only view of the index; safe to use from a worker thread of its own."""

    def search(self, query: SearchQuery) -> SearchPage: ...

    def context(
        self, chat_id: int, msg_id: int, before: int = 3, after: int = 3
    ) -> tuple[ContextMessage, ...]: ...

    def chats(self) -> tuple[ChatChoice, ...]: ...

    def status(self) -> IndexStatus: ...

    def close(self) -> None: ...
