from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chatradar.domain.models import (
    ChatInfo,
    Message,
    MessageFilter,
    RawKind,
    RawRecord,
    SearchFilters,
    Source,
    StageResult,
    UpsertResult,
)
from chatradar.domain.text import content_hash
from chatradar.pipeline.base import NORMALIZE_VERSION, STAGE_COLUMNS, STAGE_ORDER, later_stages
from chatradar.services.normalize import normalize_records
from chatradar.services.queries import ReadServices

if TYPE_CHECKING:
    from collections.abc import Sequence

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
CHAT = ChatInfo(source=Source.TELEGRAM, chat_id="-100500", title="Synthetic", username="demo")


def _record(msg_id: int, kind: RawKind = RawKind.TG_DESKTOP) -> RawRecord:
    return RawRecord(
        source=Source.TELEGRAM,
        kind=kind,
        chat_id=CHAT.chat_id,
        fetched_at=NOW,
        payload={"id": msg_id, "text": f"message {msg_id}"},
    )


def _map(record: RawRecord, chat: ChatInfo) -> Message | None:
    if record.payload["id"] == 0:
        return None
    raw = str(record.payload["text"])
    return Message(
        source=record.source,
        chat_id=record.chat_id,
        msg_id=str(record.payload["id"]),
        author_id=None,
        date=NOW,
        text=raw,
        text_raw=raw,
        link=f"https://t.me/{chat.username}/{record.payload['id']}",
        content_hash=content_hash(text_raw=raw, media_type="none", reply_to=None),
    )


class FakeChats:
    def __init__(self) -> None:
        self.lookups = 0

    async def get_chat(self, source: Source, chat_id: str) -> ChatInfo | None:
        self.lookups += 1
        return CHAT if chat_id == CHAT.chat_id else None


class FakeMessages:
    def __init__(self) -> None:
        self.batches: list[tuple[list[Message], int]] = []

    async def upsert_many(
        self, messages: Sequence[Message], normalize_version: int
    ) -> UpsertResult:
        self.batches.append((list(messages), normalize_version))
        return UpsertResult(inserted=len(messages))


async def test_normalize_records_maps_skips_and_batches() -> None:
    chats, messages = FakeChats(), FakeMessages()
    records = [_record(i) for i in range(0, 1201)]

    result = await normalize_records(
        records,
        mappers={RawKind.TG_DESKTOP: _map},
        chats=chats,  # type: ignore[arg-type]
        messages=messages,  # type: ignore[arg-type]
    )

    assert result == UpsertResult(inserted=1200)
    assert [len(batch) for batch, _ in messages.batches] == [500, 500, 200]
    assert all(version == NORMALIZE_VERSION for _, version in messages.batches)
    assert chats.lookups == 1
    assert messages.batches[0][0][0].link == "https://t.me/demo/1"


def test_stage_contract_is_consistent() -> None:
    assert set(STAGE_COLUMNS) == set(STAGE_ORDER)
    assert later_stages("normalize") == STAGE_ORDER
    assert later_stages("noise") == ("enrich", "threads", "index")
    assert later_stages("index") == ()


def test_stage_result_accepts_list_values() -> None:
    result = StageResult(
        key=(Source.TELEGRAM, "-100500", "1"),
        values={"urls": ["https://gub.uy"], "lang": "es", "is_question": True},
    )

    assert result.values["urls"] == ["https://gub.uy"]


class FakeQueries:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def pipeline_stats(self, stage_versions: Sequence[tuple[str, int]]) -> Any:
        self.calls.append(("pipeline_stats", list(stage_versions)))

    async def list_messages(self, filters: MessageFilter) -> Any:
        self.calls.append(("list_messages", filters))


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, filters: SearchFilters) -> list[Any]:
        self.queries.append(query)
        return []


async def test_read_services_delegate_and_skip_blank_search() -> None:
    queries, search = FakeQueries(), FakeSearch()
    read = ReadServices(
        queries=queries,  # type: ignore[arg-type]
        search_index=search,  # type: ignore[arg-type]
        stage_versions=[("noise", 1)],
    )

    await read.pipeline()
    await read.messages(MessageFilter(chat_id="-100500"))
    assert await read.search("   ", SearchFilters()) == []
    await read.search("rent", SearchFilters())

    assert queries.calls[0] == ("pipeline_stats", [("noise", 1)])
    assert queries.calls[1][0] == "list_messages"
    assert search.queries == ["rent"]
