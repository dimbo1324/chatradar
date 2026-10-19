from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from chatradar.domain.models import RawRecord, Source
from chatradar.storage.raw_jsonl import JsonlRawStore
from tests.unit.connectors.fakes import chat, telethon_record

if TYPE_CHECKING:
    from pathlib import Path

A, B = "-1001", "-1002"


async def _all(
    store: JsonlRawStore, source: Source | None = None, chat_id: str | None = None
) -> list[RawRecord]:
    return [r async for r in store.read(source, chat_id)]


async def test_append_writes_one_file_per_chat(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)

    written = await store.append(
        [telethon_record(A, 1), telethon_record(B, 1), telethon_record(A, 2)]
    )

    assert written == 3
    files_a = list((tmp_path / "telegram" / A).glob("*.jsonl"))
    files_b = list((tmp_path / "telegram" / B).glob("*.jsonl"))
    assert len(files_a) == len(files_b) == 1
    lines = files_a[0].read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["payload"]["id"] for line in lines] == [1, 2]
    assert files_a[0].name.endswith("Z-000000.jsonl")


async def test_append_nothing(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)

    assert await store.append([]) == 0
    assert not tmp_path.joinpath("telegram").exists()


async def test_read_replays_in_write_order_and_filters(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)
    await store.append([telethon_record(A, 1), telethon_record(A, 2)])
    await store.append([telethon_record(B, 1)])
    await store.append([telethon_record(A, 3, text="edited")])

    everything = await _all(store)
    only_a = await _all(store, chat_id=A)

    assert [(r.chat_id, r.payload["id"]) for r in everything] == [
        (A, 1), (A, 2), (A, 3), (B, 1),
    ]  # fmt: skip
    assert [r.payload["id"] for r in only_a] == [1, 2, 3]
    assert everything[0] == telethon_record(A, 1)
    assert await _all(store, source=Source.WHATSAPP) == []
    assert await _all(store, chat_id="-404") == []


async def test_read_of_an_empty_store(tmp_path: Path) -> None:
    assert await _all(JsonlRawStore(tmp_path / "missing")) == []


async def test_truncated_last_line_is_skipped_with_a_warning(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)
    await store.append([telethon_record(A, 1), telethon_record(A, 2)])
    [path] = (tmp_path / "telegram" / A).glob("*.jsonl")
    content = path.read_text(encoding="utf-8")
    path.write_text(content[: len(content) - 20], encoding="utf-8", newline="\n")

    with capture_logs() as logs:
        records = await _all(store)

    assert [r.payload["id"] for r in records] == [1]
    assert [entry["event"] for entry in logs] == ["raw.truncated_line"]


async def test_corrupt_line_in_the_middle_raises(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)
    await store.append([telethon_record(A, 1)])
    [path] = (tmp_path / "telegram" / A).glob("*.jsonl")
    path.write_text("{broken\n" + path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        await _all(store)


async def test_invalid_record_raises(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)
    await store.append([telethon_record(A, 1)])
    [path] = (tmp_path / "telegram" / A).glob("*.jsonl")
    path.write_text('{"source": "telegram"}\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        await _all(store)


async def test_chat_catalog_round_trip(tmp_path: Path) -> None:
    store = JsonlRawStore(tmp_path)
    first, second = chat("-1001"), chat("-1002", username=None)

    await store.save_chats([first, second])
    await store.save_chats([first.model_copy(update={"title": "Renamed"})])
    await store.append([telethon_record("-1001", 1)])

    assert await store.load_chats() == [first.model_copy(update={"title": "Renamed"}), second]
    assert [r.payload["id"] for r in await _all(store)] == [1]
