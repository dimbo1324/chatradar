"""In-memory fakes of the repository ports and the live connector."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from chatradar.domain.models import (
    ChatInfo,
    ChatKind,
    Message,
    MessageKey,
    RawKind,
    RawRecord,
    Source,
    StageResult,
    StoredMessage,
    SyncState,
    Thread,
    UpsertResult,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "tg_export"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


class FakeChats:
    def __init__(self, chats: Sequence[ChatInfo] = ()) -> None:
        self.chats: dict[tuple[Source, str], ChatInfo] = {(c.source, c.chat_id): c for c in chats}
        self.states: dict[tuple[Source, str], SyncState] = {}
        self.state_history: list[SyncState] = []

    async def upsert_chats(self, chats: Sequence[ChatInfo]) -> None:
        for chat in chats:
            self.chats[(chat.source, chat.chat_id)] = chat

    async def get_chat(self, source: Source, chat_id: str) -> ChatInfo | None:
        return self.chats.get((source, chat_id))

    async def list_chats(self) -> list[ChatInfo]:
        return list(self.chats.values())

    async def get_sync_state(self, source: Source, chat_id: str) -> SyncState | None:
        return self.states.get((source, chat_id))

    async def set_sync_state(self, state: SyncState) -> None:
        self.states[(state.source, state.chat_id)] = state
        self.state_history.append(state)


class FakeMessages:
    def __init__(self) -> None:
        self.rows: dict[MessageKey, Message] = {}
        self.calls = 0

    async def upsert_many(
        self, messages: Sequence[Message], normalize_version: int
    ) -> UpsertResult:
        self.calls += 1
        keys = [m.key for m in messages]
        assert len(keys) == len(set(keys)), "one upsert batch holds a message twice"
        inserted = updated = unchanged = 0
        for message in messages:
            old = self.rows.get(message.key)
            if old is None:
                inserted += 1
            elif old.content_hash != message.content_hash:
                updated += 1
            else:
                unchanged += 1
                continue
            self.rows[message.key] = message
        return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)

    async def pending_for(
        self, stage: str, version: int, depends_on: str | None, limit: int
    ) -> list[StoredMessage]:
        raise NotImplementedError

    async def mark(self, stage: str, version: int, results: Sequence[StageResult]) -> None:
        raise NotImplementedError

    async def get_many(self, keys: Sequence[MessageKey]) -> dict[MessageKey, StoredMessage]:
        raise NotImplementedError

    async def chat_window(
        self, source: Source, chat_id: str, since: datetime
    ) -> list[StoredMessage]:
        raise NotImplementedError

    async def save_threads(
        self, source: Source, chat_id: str, since: datetime, threads: Sequence[Thread]
    ) -> None:
        raise NotImplementedError

    async def reset_stage(self, stage: str) -> int:
        raise NotImplementedError


class MemoryRawStore:
    def __init__(self, events: list[str] | None = None) -> None:
        self.records: list[RawRecord] = []
        self.events = events if events is not None else []

    async def append(self, records: Sequence[RawRecord]) -> int:
        self.records.extend(records)
        self.events.append(f"append:{len(records)}")
        return len(records)

    async def read(
        self, source: Source | None = None, chat_id: str | None = None
    ) -> AsyncIterator[RawRecord]:
        for record in self.records:
            if (source is None or record.source is source) and (
                chat_id is None or record.chat_id == chat_id
            ):
                yield record


def chat(chat_id: str = "-1001700000001", username: str | None = "expats_demo") -> ChatInfo:
    return ChatInfo(
        source=Source.TELEGRAM,
        chat_id=chat_id,
        title=f"Chat {chat_id}",
        username=username,
        kind=ChatKind.SUPERGROUP,
    )


def telethon_record(chat_id: str, msg_id: int, text: str = "hello") -> RawRecord:
    return RawRecord(
        source=Source.TELEGRAM,
        kind=RawKind.TELETHON,
        chat_id=chat_id,
        fetched_at=NOW,
        payload={
            "_": "Message",
            "id": msg_id,
            "date": "2026-10-01T10:00:00+00:00",
            "message": text,
            "from_id": {"_": "PeerUser", "user_id": 42},
        },
    )


class FakeConnector:
    """Serves a fixed message history per chat; records every request."""

    source = Source.TELEGRAM

    def __init__(self, history: dict[str, list[RawRecord]], resolved: ChatInfo | None = None):
        self.history = history
        self.resolved = resolved
        self.requests: list[tuple[str, str, str | None]] = []

    async def resolve(self, ref: str) -> ChatInfo:
        assert self.resolved is not None
        self.requests.append(("resolve", ref, None))
        return self.resolved

    async def fetch(self, chat: ChatInfo, since_id: str | None) -> AsyncIterator[RawRecord]:
        self.requests.append(("fetch", chat.chat_id, since_id))
        floor = int(since_id) if since_id else 0
        for record in self.history.get(chat.chat_id, []):
            if int(record.payload["id"]) > floor:
                yield record

    async def fetch_recent(self, chat: ChatInfo, days: int) -> AsyncIterator[RawRecord]:
        self.requests.append(("recent", chat.chat_id, str(days)))
        for record in self.history.get(chat.chat_id, [])[-2:]:
            yield record
