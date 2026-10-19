"""The whole service on real adapters: import → pipeline → search → web API → rebuild.

Also the contract check the parallel packages lacked: the real adapters must satisfy the
ports (pyright verifies the assignments below).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from chatradar.config import Settings
from chatradar.domain.models import MessageFilter, SearchFilters
from chatradar.pipeline.registry import stage_versions
from chatradar.services.container import open_runtime
from chatradar.services.ingest import import_tg_export
from chatradar.services.process import process
from chatradar.services.rebuild import rebuild
from chatradar.web.app import create_app

if TYPE_CHECKING:
    from chatradar.domain.ports import (
        ChatCatalog,
        ChatRepository,
        DerivedDataStore,
        MessageRepository,
        QueryRepository,
        RawStore,
        SearchIndex,
    )
    from chatradar.services.container import Runtime

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tg_export" / "supergroup_result.json"


def _ports_are_satisfied(rt: Runtime) -> None:
    chats: ChatRepository = rt.repo
    messages: MessageRepository = rt.repo
    queries: QueryRepository = rt.repo
    store: DerivedDataStore = rt.repo
    search: SearchIndex = rt.search
    raw: RawStore = rt.raw
    catalog: ChatCatalog = rt.raw
    del chats, messages, queries, store, search, raw, catalog


async def test_import_process_search_rebuild(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    async with open_runtime(settings) as rt:
        _ports_are_satisfied(rt)
        report = await import_tg_export(
            FIXTURE,
            username="expats_mvd_demo",
            raw=rt.raw,
            chats=rt.repo,
            messages=rt.repo,
            catalog=rt.raw,
        )
        assert report.records == 60
        assert report.result.inserted > 0

        first = await process(rt.stage_deps)
        assert first["noise"] > 0
        assert await process(rt.stage_deps) == dict.fromkeys(first, 0)

        stats = await rt.read.pipeline()
        assert all(s.pending == 0 for s in stats.stages)

        noise = await rt.read.messages(MessageFilter(is_noise=True, limit=500))
        assert noise.total > 0
        assert all(m.noise_reason for m in noise.items)
        assert all(m.thread_id is None for m in noise.items)

        hits = await rt.read.search("alquiler", SearchFilters())
        assert hits
        assert "[[" in hits[0].snippet
        assert hits[0].link is not None
        assert hits[0].link.startswith("https://t.me/expats_mvd_demo/")

        detail = await rt.read.thread(hits[0].thread.thread_id)
        assert detail is not None
        assert detail.messages

        summary = (await rt.read.chats())[0]
        before = (summary.message_count, summary.noise_count, summary.thread_count)

        rebuilt = await rebuild(
            raw=rt.raw,
            catalog=rt.raw,
            store=rt.repo,
            chats=rt.repo,
            messages=rt.repo,
            deps=rt.stage_deps,
        )
        assert rebuilt.result.inserted == summary.message_count
        after = (await rt.read.chats())[0]
        assert (after.message_count, after.noise_count, after.thread_count) == before
        assert after.chat.username == "expats_mvd_demo"
        assert await rt.read.search("alquiler", SearchFilters())

        with TestClient(create_app(rt.read)) as client:
            assert client.get("/api/chats").json()[0]["message_count"] == before[0]
            pipeline = client.get("/api/pipeline").json()
            assert [s["stage"] for s in pipeline["stages"]] == [n for n, _ in stage_versions()]
            found = client.get("/api/search", params={"q": "alquiler"}).json()
            assert found
            thread = client.get(f"/api/threads/{quote(found[0]['thread']['thread_id'], safe='')}")
            assert thread.status_code == 200
            assert client.get("/").status_code == 200
