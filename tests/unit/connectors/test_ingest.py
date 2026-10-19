from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.domain.models import RawKind, Source
from chatradar.services.ingest import MAPPERS, import_tg_export, reingest_all
from chatradar.storage.raw_jsonl import JsonlRawStore
from tests.unit.connectors.fakes import (
    FIXTURES,
    FakeChats,
    FakeMessages,
    MemoryRawStore,
    chat,
    telethon_record,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_mappers_cover_every_raw_kind() -> None:
    assert set(MAPPERS) == set(RawKind)


async def test_import_registers_chats_stores_raw_and_normalizes() -> None:
    raw, chats, messages = MemoryRawStore(), FakeChats(), FakeMessages()

    report = await import_tg_export(
        FIXTURES / "supergroup_result.json",
        username="expats_demo",
        raw=raw,
        chats=chats,
        messages=messages,
    )

    [imported] = report.chats
    assert imported.chat_id == "-1001700000001"
    assert await chats.get_chat(Source.TELEGRAM, imported.chat_id) == imported
    assert report.records == len(raw.records) == 60
    assert report.result.inserted == len(messages.rows) == 60
    assert {m.link for m in messages.rows.values()} >= {"https://t.me/expats_demo/1"}


async def test_import_twice_changes_nothing_in_the_database() -> None:
    raw, chats, messages = MemoryRawStore(), FakeChats(), FakeMessages()
    path = FIXTURES / "full_account_result.json"

    await import_tg_export(path, raw=raw, chats=chats, messages=messages)
    second = await import_tg_export(path, raw=raw, chats=chats, messages=messages)

    assert len(chats.chats) == 2
    assert len(messages.rows) == 7
    assert (second.result.inserted, second.result.unchanged) == (0, 7)


async def test_reingest_rebuilds_the_database_from_raw(tmp_path: Path) -> None:
    raw = JsonlRawStore(tmp_path / "raw")
    await import_tg_export(
        FIXTURES / "supergroup_result.json",
        username="expats_demo",
        raw=raw,
        chats=FakeChats(),
        messages=FakeMessages(),
        catalog=raw,
    )
    await raw.append(
        [
            telethon_record("-1001700000001", 900, "first"),
            telethon_record("-1001700000001", 900, "first, edited"),
        ]
    )
    chats, messages = FakeChats(), FakeMessages()

    result = await reingest_all(raw=raw, chats=chats, messages=messages, catalog=raw, batch_size=7)

    assert result.inserted == len(messages.rows) == 61
    assert messages.calls == 9
    edited = messages.rows[(Source.TELEGRAM, "-1001700000001", "900")]
    assert edited.text == "first, edited"
    restored = await chats.get_chat(Source.TELEGRAM, "-1001700000001")
    assert restored is not None
    assert restored.username == "expats_demo"
    assert edited.link == "https://t.me/expats_demo/900"


async def test_reingest_without_catalog_uses_known_chats() -> None:
    raw = MemoryRawStore()
    await raw.append([telethon_record("-1009", 1)])
    chats, messages = FakeChats([chat("-1009", username="known")]), FakeMessages()

    result = await reingest_all(raw=raw, chats=chats, messages=messages)

    assert result.inserted == 1
    assert messages.rows[(Source.TELEGRAM, "-1009", "1")].link == "https://t.me/known/1"


async def test_reingest_of_an_empty_store() -> None:
    result = await reingest_all(raw=MemoryRawStore(), chats=FakeChats(), messages=FakeMessages())

    assert (result.inserted, result.updated, result.unchanged) == (0, 0, 0)
