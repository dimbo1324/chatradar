"""Ports are structural interfaces (Protocol). Adapters do not inherit from them.

This module is the contract between the packages built in parallel (connectors, storage,
pipeline, web). Change it only through the lead, together with every implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import datetime

    from chatradar.domain.models import (
        ChatInfo,
        ChatSummary,
        Message,
        MessageFilter,
        MessageKey,
        MessagePage,
        PipelineStats,
        RawRecord,
        SearchFilters,
        Source,
        StageResult,
        StoredMessage,
        SyncState,
        Thread,
        ThreadDetail,
        ThreadHit,
        UpsertResult,
    )


class Connector(Protocol):
    """A live source of messages (Telethon). File importers do not need this port."""

    source: Source

    async def list_chats(self) -> list[ChatInfo]: ...

    def fetch(self, chat: ChatInfo, since_id: str | None) -> AsyncIterator[RawRecord]:
        """Messages with id > since_id (all when None), oldest first."""
        ...


class Mapper(Protocol):
    """Pure function: one raw record → one normalized message, or None to skip it."""

    def __call__(self, record: RawRecord, chat: ChatInfo) -> Message | None: ...


class RawStore(Protocol):
    """Append-only store of raw records (`data/raw/<source>/<chat_id>/<run>.jsonl`)."""

    async def append(self, records: Sequence[RawRecord]) -> int:
        """Persist records (any mix of chats) durably; returns how many were written."""
        ...

    def read(
        self, source: Source | None = None, chat_id: str | None = None
    ) -> AsyncIterator[RawRecord]:
        """Every stored record, filtered when arguments are given, in write order per chat."""
        ...


class ChatCatalog(Protocol):
    """Chat metadata kept beside the raw data, so a rebuild restores titles and links.

    `RawRecord` carries no chat title or username; `JsonlRawStore` implements this.
    """

    async def save_chats(self, chats: Sequence[ChatInfo]) -> None: ...
    async def load_chats(self) -> list[ChatInfo]: ...


class DerivedDataStore(Protocol):
    async def clear_derived(self) -> None:
        """Delete messages, threads and the search index; keep chats and sync state."""
        ...


class ChatRepository(Protocol):
    async def upsert_chats(self, chats: Sequence[ChatInfo]) -> None: ...
    async def get_chat(self, source: Source, chat_id: str) -> ChatInfo | None: ...
    async def list_chats(self) -> list[ChatInfo]: ...
    async def get_sync_state(self, source: Source, chat_id: str) -> SyncState | None: ...
    async def set_sync_state(self, state: SyncState) -> None: ...


class MessageRepository(Protocol):
    """The write side used by ingestion and the pipeline stages.

    Version columns: `<stage>_v` for `normalize` and every stage in `STAGE_ORDER`.
    """

    async def upsert_many(
        self, messages: Sequence[Message], normalize_version: int
    ) -> UpsertResult:
        """Insert new messages; on a changed `content_hash` update them and reset every
        stage version to NULL; on an equal hash change nothing. Sets `normalize_v`."""
        ...

    async def pending_for(
        self, stage: str, version: int, depends_on: str | None, limit: int
    ) -> list[StoredMessage]:
        """Messages where `<stage>_v IS NULL OR < version` and, when given,
        `<depends_on>_v IS NOT NULL`; ordered by source, chat_id, date, msg_id."""
        ...

    async def mark(self, stage: str, version: int, results: Sequence[StageResult]) -> None:
        """In one transaction: write each result's values (only the stage's columns), set
        `<stage>_v = version`, and reset the version of every LATER stage to NULL for those
        messages."""
        ...

    async def get_many(self, keys: Sequence[MessageKey]) -> dict[MessageKey, StoredMessage]: ...

    async def chat_window(
        self, source: Source, chat_id: str, since: datetime
    ) -> list[StoredMessage]:
        """Every message of the chat with `date >= since`, ordered by date, msg_id."""
        ...

    async def save_threads(
        self, source: Source, chat_id: str, since: datetime, threads: Sequence[Thread]
    ) -> None:
        """Replace the chat's threads that start at or after `since` with `threads`."""
        ...

    async def reset_stage(self, stage: str) -> int:
        """Set `<stage>_v` (and every later stage's) to NULL everywhere; returns rows touched."""
        ...


class QueryRepository(Protocol):
    """The read side used by the web panel and the API."""

    async def chat_summaries(self) -> list[ChatSummary]: ...
    async def pipeline_stats(self, stage_versions: Sequence[tuple[str, int]]) -> PipelineStats: ...
    async def list_messages(self, filters: MessageFilter) -> MessagePage: ...
    async def get_thread(self, thread_id: str) -> ThreadDetail | None: ...
    async def sample(self, *, is_noise: bool, n: int) -> list[StoredMessage]: ...
    async def noise_reasons(self) -> dict[str, int]: ...


class SearchIndex(Protocol):
    async def index_threads(self, thread_ids: Sequence[str]) -> None:
        """(Re)build the search entries of these threads from their non-noise messages;
        a thread that no longer exists is removed from the index."""
        ...

    async def search(self, query: str, filters: SearchFilters) -> list[ThreadHit]: ...

    async def rebuild(self) -> None:
        """Recreate the whole index from the current threads."""
        ...
