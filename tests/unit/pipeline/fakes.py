"""In-memory `MessageRepository` and `SearchIndex` following the port docstrings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from chatradar.domain.models import MediaType, Source, StoredMessage
from chatradar.domain.text import content_hash
from chatradar.pipeline.base import STAGE_COLUMNS, StageDeps, later_stages

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chatradar.domain.models import (
        Message,
        MessageKey,
        SearchFilters,
        StageResult,
        Thread,
        ThreadHit,
        UpsertResult,
    )

CHAT_ID = "-100777"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def make_message(
    msg_id: int | str,
    text: str = "",
    *,
    minutes: float = 0,
    chat_id: str = CHAT_ID,
    reply_to: int | str | None = None,
    topic_id: str | None = None,
    media: MediaType = MediaType.NONE,
    service: bool = False,
    **stored: Any,
) -> StoredMessage:
    """A stored message `minutes` after `T0`; extra keywords set pipeline columns."""
    reply = None if reply_to is None else str(reply_to)
    return StoredMessage(
        source=Source.TELEGRAM,
        chat_id=chat_id,
        msg_id=str(msg_id),
        author_id=None,
        date=T0 + timedelta(minutes=minutes),
        text=text,
        text_raw=text,
        reply_to=reply,
        topic_id=topic_id,
        media_type=media,
        is_service=service,
        content_hash=content_hash(text_raw=text, media_type=media.value, reply_to=reply),
        **stored,
    )


def _order(msg: StoredMessage) -> tuple[datetime, str]:
    return (msg.date, msg.msg_id)


class FakeMessages:
    def __init__(self, messages: Sequence[StoredMessage] = ()) -> None:
        self.rows: dict[MessageKey, StoredMessage] = {m.key: m for m in messages}
        self.threads: dict[str, Thread] = {}
        self.window_calls: list[tuple[str, datetime]] = []
        self.marked: list[tuple[str, int, int]] = []

    def add(self, *messages: StoredMessage) -> None:
        for msg in messages:
            self.rows[msg.key] = msg

    def row(self, msg_id: int | str, chat_id: str = CHAT_ID) -> StoredMessage:
        return self.rows[(Source.TELEGRAM, chat_id, str(msg_id))]

    async def upsert_many(
        self, messages: Sequence[Message], normalize_version: int
    ) -> UpsertResult:
        raise NotImplementedError

    async def pending_for(
        self, stage: str, version: int, depends_on: str | None, limit: int
    ) -> list[StoredMessage]:
        def wanted(msg: StoredMessage) -> bool:
            done = msg.versions.get(stage)
            if done is not None and done >= version:
                return False
            return depends_on is None or msg.versions.get(depends_on) is not None

        found = [m for m in self.rows.values() if wanted(m)]
        found.sort(key=lambda m: (m.source, m.chat_id, m.date, m.msg_id))
        return found[:limit]

    async def mark(self, stage: str, version: int, results: Sequence[StageResult]) -> None:
        allowed = set(STAGE_COLUMNS[stage])
        updates: dict[MessageKey, StoredMessage] = {}
        for result in results:
            extra = set(result.values) - allowed
            if extra:
                msg = f"stage {stage} may not write {sorted(extra)}"
                raise ValueError(msg)
            current = self.rows[result.key]
            values = {k: tuple(v) if isinstance(v, list) else v for k, v in result.values.items()}
            versions = {k: v for k, v in current.versions.items() if k not in later_stages(stage)}
            versions[stage] = version
            updates[result.key] = current.model_copy(update={**values, "versions": versions})
        self.rows.update(updates)
        self.marked.append((stage, version, len(results)))

    async def get_many(self, keys: Sequence[MessageKey]) -> dict[MessageKey, StoredMessage]:
        return {key: self.rows[key] for key in keys if key in self.rows}

    async def chat_window(
        self, source: Source, chat_id: str, since: datetime
    ) -> list[StoredMessage]:
        self.window_calls.append((chat_id, since))
        found = [
            m
            for m in self.rows.values()
            if m.source == source and m.chat_id == chat_id and m.date >= since
        ]
        return sorted(found, key=_order)

    async def save_threads(
        self, source: Source, chat_id: str, since: datetime, threads: Sequence[Thread]
    ) -> None:
        self.threads = {
            tid: t
            for tid, t in self.threads.items()
            if not (t.source == source and t.chat_id == chat_id and t.started_at >= since)
        }
        for thread in threads:
            self.threads[thread.thread_id] = thread

    async def reset_stage(self, stage: str) -> int:
        cleared = {stage, *later_stages(stage)}
        touched = 0
        for key, msg in list(self.rows.items()):
            if cleared & set(msg.versions):
                touched += 1
                versions = {k: v for k, v in msg.versions.items() if k not in cleared}
                self.rows[key] = msg.model_copy(update={"versions": versions})
        return touched


class FakeSearch:
    def __init__(self, messages: FakeMessages) -> None:
        self._messages = messages
        self.entries: dict[str, str] = {}
        self.calls: list[list[str]] = []

    async def index_threads(self, thread_ids: Sequence[str]) -> None:
        self.calls.append(list(thread_ids))
        for thread_id in thread_ids:
            if thread_id not in self._messages.threads:
                self.entries.pop(thread_id, None)
                continue
            members = sorted(
                (
                    m
                    for m in self._messages.rows.values()
                    if m.thread_id == thread_id and not m.is_noise
                ),
                key=_order,
            )
            self.entries[thread_id] = "\n".join(m.text for m in members)

    async def search(self, query: str, filters: SearchFilters) -> list[ThreadHit]:
        raise NotImplementedError

    async def rebuild(self) -> None:
        await self.index_threads(list(self._messages.threads))


def make_deps(messages: Sequence[StoredMessage] = ()) -> tuple[StageDeps, FakeMessages, FakeSearch]:
    repo = FakeMessages(messages)
    search = FakeSearch(repo)
    return StageDeps(messages=repo, search=search), repo, search
