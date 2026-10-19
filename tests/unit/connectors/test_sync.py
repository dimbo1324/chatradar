from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from chatradar.domain.models import ChatInfo, Message, RawRecord, Source, SyncState, UpsertResult
from chatradar.services.sync import add_chat, sync_chats
from chatradar.storage.raw_jsonl import JsonlRawStore
from tests.unit.connectors.fakes import (
    FakeChats,
    FakeConnector,
    FakeMessages,
    MemoryRawStore,
    chat,
    telethon_record,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

A, B = "-1001", "-1002"


def _history(chat_id: str, count: int) -> list[RawRecord]:
    return [telethon_record(chat_id, msg_id) for msg_id in range(1, count + 1)]


class OrderedMessages(FakeMessages):
    """Records when normalization happens relative to raw writes and state updates."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def upsert_many(
        self, messages: Sequence[Message], normalize_version: int
    ) -> UpsertResult:
        self.events.append("upsert")
        return await super().upsert_many(messages, normalize_version)


class OrderedChats(FakeChats):
    def __init__(self, chats: list[ChatInfo], events: list[str]) -> None:
        super().__init__(chats)
        self.events = events

    async def set_sync_state(self, state: SyncState) -> None:
        self.events.append(f"state:{state.last_id}")
        await super().set_sync_state(state)


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def test_add_chat_resolves_and_tracks() -> None:
    target = chat(A)
    connector = FakeConnector({}, resolved=target)
    chats = FakeChats()
    catalog = MemoryCatalog()

    added = await add_chat(connector, "@expats_demo", chats, catalog)

    assert added == target
    assert await chats.list_chats() == [target]
    assert catalog.saved == [target]
    assert connector.requests == [("resolve", "@expats_demo", None)]


class MemoryCatalog:
    def __init__(self) -> None:
        self.saved: list[ChatInfo] = []

    async def save_chats(self, chats: Sequence[ChatInfo]) -> None:
        self.saved.extend(chats)

    async def load_chats(self) -> list[ChatInfo]:
        return self.saved


async def test_raw_is_written_before_last_id_moves_and_before_normalizing() -> None:
    events: list[str] = []
    raw = MemoryRawStore(events)
    chats = OrderedChats([chat(A)], events)
    messages = OrderedMessages(events)
    connector = FakeConnector({A: _history(A, 5)})

    report = await sync_chats(
        connector, raw=raw, chats=chats, messages=messages, pause_sec=0, batch_size=2
    )

    assert events == [
        "append:2", "state:2", "upsert",
        "append:2", "state:4", "upsert",
        "append:1", "state:5", "upsert",
        "state:5",
    ]  # fmt: skip
    assert report.fetched == 5
    assert report.result.inserted == 5
    assert report.chats[0].last_id == "5"


async def test_incremental_sync_starts_after_last_id() -> None:
    chats = FakeChats([chat(A)])
    chats.states[(Source.TELEGRAM, A)] = SyncState(source=Source.TELEGRAM, chat_id=A, last_id="3")
    connector = FakeConnector({A: _history(A, 5)})
    raw = MemoryRawStore()

    report = await sync_chats(connector, raw=raw, chats=chats, messages=FakeMessages(), pause_sec=0)

    assert connector.requests == [("fetch", A, "3")]
    assert [r.payload["id"] for r in raw.records] == [4, 5]
    assert report.chats[0].fetched == 2
    state = chats.states[(Source.TELEGRAM, A)]
    assert state.last_id == "5"
    assert state.last_sync_at is not None


async def test_nothing_new_keeps_last_id_and_records_the_sync_time() -> None:
    chats = FakeChats([chat(A)])
    chats.states[(Source.TELEGRAM, A)] = SyncState(source=Source.TELEGRAM, chat_id=A, last_id="5")
    raw = MemoryRawStore()

    report = await sync_chats(
        FakeConnector({A: _history(A, 5)}),
        raw=raw,
        chats=chats,
        messages=FakeMessages(),
        pause_sec=0,
    )

    assert raw.records == []
    assert report.fetched == 0
    assert chats.states[(Source.TELEGRAM, A)].last_id == "5"
    assert chats.states[(Source.TELEGRAM, A)].last_sync_at is not None


async def test_recheck_catches_edits_without_moving_last_id_back() -> None:
    chats = FakeChats([chat(A)])
    messages = FakeMessages()
    history = _history(A, 4)
    connector = FakeConnector({A: history})
    await sync_chats(connector, raw=MemoryRawStore(), chats=chats, messages=messages, pause_sec=0)
    history[2] = telethon_record(A, 3, "edited text")

    report = await sync_chats(
        connector,
        raw=MemoryRawStore(),
        chats=chats,
        messages=messages,
        pause_sec=0,
        recheck_days=7,
    )

    assert connector.requests[-2:] == [("fetch", A, "4"), ("recent", A, "7")]
    assert report.chats[0].rechecked == 2
    assert (report.result.updated, report.result.unchanged) == (1, 1)
    assert messages.rows[(Source.TELEGRAM, A, "3")].text == "edited text"
    assert [s.last_id for s in chats.state_history][-2:] == ["4", "4"]


async def test_pauses_between_chats_and_filters_by_id() -> None:
    other_source = ChatInfo(source=Source.WHATSAPP, chat_id="w1", title="WhatsApp")
    chats = FakeChats([chat(A), chat(B), chat("-1003"), other_source])
    connector = FakeConnector({A: _history(A, 1), B: _history(B, 1)})
    sleeps = Sleeps()

    report = await sync_chats(
        connector,
        raw=MemoryRawStore(),
        chats=chats,
        messages=FakeMessages(),
        chat_ids={A, B},
        pause_sec=2.5,
        sleep=sleeps,
    )

    assert [c.chat_id for c in report.chats] == [A, B]
    assert sleeps.calls == [2.5]
    assert all(request[1] != "w1" for request in connector.requests)


class FailingConnector(FakeConnector):
    async def fetch(self, chat: ChatInfo, since_id: str | None) -> AsyncIterator[RawRecord]:
        for record in _history(chat.chat_id, 3):
            yield record
        raise ConnectionError("network down")


async def test_failure_mid_chat_keeps_the_progress_already_stored(tmp_path: Path) -> None:
    raw = JsonlRawStore(tmp_path)
    chats = FakeChats([chat(A)])

    with pytest.raises(ConnectionError):
        await sync_chats(
            FailingConnector({}),
            raw=raw,
            chats=chats,
            messages=FakeMessages(),
            pause_sec=0,
            batch_size=2,
        )

    assert chats.states[(Source.TELEGRAM, A)].last_id == "2"
    assert [r.payload["id"] async for r in raw.read()] == [1, 2]
