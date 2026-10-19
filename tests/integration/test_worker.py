from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from chatradar.config import Settings
from chatradar.domain.models import ChatInfo, RawKind, RawRecord, Source
from chatradar.services.container import open_runtime
from chatradar.services.worker import run_forever

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

pytestmark = pytest.mark.integration

CHAT = ChatInfo(source=Source.TELEGRAM, chat_id="-100777", title="Synthetic", username="syn")


def _record(msg_id: int, text: str, reply_to: int | None = None) -> RawRecord:
    return RawRecord(
        source=Source.TELEGRAM,
        kind=RawKind.TELETHON,
        chat_id=CHAT.chat_id,
        fetched_at=datetime.now(UTC),
        payload={
            "_": "Message",
            "id": msg_id,
            "date": f"2026-10-0{msg_id}T12:00:00+00:00",
            "message": text,
            "from_id": {"_": "PeerUser", "user_id": 1},
            "reply_to": {"_": "MessageReplyHeader", "reply_to_msg_id": reply_to}
            if reply_to
            else None,
        },
    )


class FakeTelegram:
    source = Source.TELEGRAM

    def __init__(self) -> None:
        self.since: list[str | None] = []
        self.rechecks = 0

    async def resolve(self, ref: str) -> ChatInfo:
        return CHAT

    async def fetch(self, chat: ChatInfo, since_id: str | None) -> AsyncIterator[RawRecord]:
        self.since.append(since_id)
        if since_id is None:
            yield _record(1, "How long does the residence permit take?")
            yield _record(2, "About three months in my case.", reply_to=1)

    async def fetch_recent(self, chat: ChatInfo, days: int) -> AsyncIterator[RawRecord]:
        self.rechecks += 1
        for _ in ():
            yield _record(0, "")


async def test_worker_syncs_processes_and_rechecks_once_a_day(tmp_path: Path) -> None:
    telegram = FakeTelegram()
    sleeps: list[float] = []

    @asynccontextmanager
    async def connect() -> AsyncGenerator[FakeTelegram]:
        yield telegram

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    settings = Settings(data_dir=tmp_path / "data")
    async with open_runtime(settings) as rt:
        await rt.repo.upsert_chats([CHAT])
        await run_forever(rt, connect, sleep=sleep, cycles=2)  # type: ignore[arg-type]

        summary = (await rt.read.chats())[0]
        state = await rt.repo.get_sync_state(Source.TELEGRAM, CHAT.chat_id)

    assert telegram.since == [None, "2"]
    assert telegram.rechecks == 1
    assert sleeps == [settings.worker.sync_interval_hours * 3600]
    assert summary.message_count == 2
    assert summary.thread_count == 1
    assert state is not None
    assert state.last_id == "2"


async def test_worker_survives_a_failing_cycle(tmp_path: Path) -> None:
    @asynccontextmanager
    async def broken() -> AsyncGenerator[FakeTelegram]:
        raise ConnectionError("network down")
        yield FakeTelegram()

    async def sleep(seconds: float) -> None:
        return None

    async with open_runtime(Settings(data_dir=tmp_path / "data")) as rt:
        await run_forever(rt, broken, sleep=sleep, cycles=2)  # type: ignore[arg-type]
