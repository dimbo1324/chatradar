from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import text

from chatradar.domain.models import SearchFilters, Source
from chatradar.storage.db.search_fts5 import Fts5SearchIndex, query_terms
from tests.integration.storage.helpers import (
    CHAT,
    OTHER,
    T0,
    make_message,
    result,
    run_pipeline,
    texts,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from chatradar.domain.models import Thread
    from chatradar.storage.db.repositories import SqlRepository

pytestmark = pytest.mark.integration

ANY = SearchFilters()
SAMPLES = texts()


async def _corpus(repo: SqlRepository, index: Fts5SearchIndex) -> list[Thread]:
    """Threads: flat (CHAT, two messages and a noisy one), bike (CHAT, an hour later),
    song (OTHER), cedula (OTHER, a day later)."""
    flat = [
        make_message(1, SAMPLES["ru_flat_rent"], minutes=0),
        make_message(2, SAMPLES["ru_flat_reply"], minutes=1, reply_to=1),
        make_message(3, "spam bicycle offer", minutes=2),
    ]
    bike = [make_message(10, SAMPLES["ru_bike"], minutes=60)]
    song = [make_message(20, SAMPLES["es_song"], chat=OTHER, minutes=0)]
    cedula = [make_message(30, SAMPLES["es_visa"], chat=OTHER, minutes=24 * 60)]
    threads = await run_pipeline(
        repo,
        [*flat, *bike, *song, *cedula],
        noise={"3": "spam"},
        threads=[flat, bike, song, cedula],
    )
    await index.index_threads([t.thread_id for t in threads])
    return threads


async def _hits(index: Fts5SearchIndex, query: str, filters: SearchFilters = ANY) -> list[str]:
    return [hit.thread.root_msg_id for hit in await index.search(query, filters)]


def test_query_terms_quote_tokens_and_use_prefixes() -> None:
    assert query_terms('NEAR(a b) "x" OR -c*') == ['"near"', '"a"', '"b"', '"x"', '"or"', '"c"']
    assert query_terms("telegram bots bots") == ['"telegr"*', '"bots"']
    assert query_terms("abcde") == ['"abcd"*']
    assert query_terms("_ ... ¿?") == []


@pytest.mark.parametrize(
    ("query", "root"),
    [
        (SAMPLES["ru_flat_query"], "1"),
        (SAMPLES["ru_bike_query"], "10"),
        (SAMPLES["ru_upper_query"], "10"),
        (SAMPLES["es_song_query_plain"], "20"),
        ("canción", "20"),
        ("CANCIÓN", "20"),
        (SAMPLES["es_visa_query"], "30"),
        ("montevideo", "30"),
    ],
)
async def test_search_finds_inflected_cyrillic_and_accented_words(
    repo: SqlRepository, index: Fts5SearchIndex, query: str, root: str
) -> None:
    await _corpus(repo, index)
    assert await _hits(index, query) == [root]


async def test_search_ignores_noise_messages(repo: SqlRepository, index: Fts5SearchIndex) -> None:
    await _corpus(repo, index)
    assert await _hits(index, "bicycle") == []


async def test_all_tokens_must_match_then_any_token(
    repo: SqlRepository, index: Fts5SearchIndex
) -> None:
    await _corpus(repo, index)
    assert await _hits(index, "montevideo cedula") == ["30"]
    assert sorted(await _hits(index, "montevideo fiesta")) == ["20", "30"]
    assert await _hits(index, "zzzz yyyy") == []


async def test_hit_has_snippet_markers_link_score_and_thread(
    repo: SqlRepository, index: Fts5SearchIndex
) -> None:
    threads = await _corpus(repo, index)
    [hit] = await index.search("montevideo", ANY)
    assert hit.thread == threads[3]
    assert "[[Montevideo]]" in hit.snippet
    assert hit.link == "https://t.me/c/600/30"
    assert hit.score > 0

    [flat] = await index.search(SAMPLES["ru_flat_query"], ANY)
    assert flat.link == "https://t.me/demo/1"
    assert flat.snippet.count("[[") == flat.snippet.count("]]") >= 2


async def test_better_matches_rank_first(repo: SqlRepository, index: Fts5SearchIndex) -> None:
    strong = [make_message(1, "router router router setup"), make_message(2, "router again")]
    weak = [make_message(10, "a long message about many things and one router", minutes=90)]
    threads = await run_pipeline(repo, [*strong, *weak], threads=[strong, weak])
    await index.index_threads([t.thread_id for t in threads])
    hits = await index.search("router", ANY)
    assert [h.thread.root_msg_id for h in hits] == ["1", "10"]
    assert hits[0].score > hits[1].score


async def test_filters_by_source_chat_dates_and_limit(
    repo: SqlRepository, index: Fts5SearchIndex
) -> None:
    await _corpus(repo, index)
    query = "montevideo fiesta"
    assert sorted(await _hits(index, query, SearchFilters(chat_id=OTHER.chat_id))) == ["20", "30"]
    assert await _hits(index, query, SearchFilters(chat_id=CHAT.chat_id)) == []
    assert await _hits(index, query, SearchFilters(source=Source.WHATSAPP)) == []
    assert len(await _hits(index, query, SearchFilters(source=Source.TELEGRAM))) == 2
    late = SearchFilters(date_from=T0 + timedelta(hours=12))
    early = SearchFilters(date_to=T0 + timedelta(hours=12))
    assert await _hits(index, query, late) == ["30"]
    assert await _hits(index, query, early) == ["20"]
    assert len(await _hits(index, query, SearchFilters(limit=1))) == 1


@pytest.mark.parametrize(
    "query",
    [
        '"',
        '"unbalanced',
        "((montevideo",
        "montevideo)",
        "NEAR(montevideo fiesta, 2)",
        "mont*",
        "*",
        "body:montevideo",
        "montevideo AND OR NOT",
        "^montevideo",
        "-montevideo",
        "'; DROP TABLE threads; --",
        "{body} : montevideo",
        "\u0000​",
        "   ",
    ],
)
async def test_hostile_input_never_raises(
    repo: SqlRepository, index: Fts5SearchIndex, query: str
) -> None:
    await _corpus(repo, index)
    hits = await index.search(query, ANY)
    if "montevideo" in query.lower():
        assert "30" in [h.thread.root_msg_id for h in hits]


async def test_marker_lookalikes_in_text_do_not_fake_matches(
    repo: SqlRepository, index: Fts5SearchIndex
) -> None:
    message = make_message(1, "see [[docs]] for the router")
    threads = await run_pipeline(repo, [message], threads=[[message]])
    await index.index_threads([threads[0].thread_id])
    [hit] = await index.search("router", ANY)
    assert "[[docs]]" not in hit.snippet
    assert "[[router]]" in hit.snippet


async def test_index_threads_replaces_and_removes_entries(
    repo: SqlRepository, index: Fts5SearchIndex, engine: AsyncEngine
) -> None:
    threads = await _corpus(repo, index)
    await index.index_threads([t.thread_id for t in threads])
    assert await _fts_rows(engine) == 4

    edited = make_message(30, "now about the harbour", chat=OTHER)
    await repo.upsert_many([edited], 1)
    await repo.mark("threads", 1, [result(edited, thread_id=threads[3].thread_id)])
    await index.index_threads([threads[3].thread_id])
    assert await _hits(index, "montevideo") == []
    assert await _hits(index, "harbour") == ["30"]

    await repo.save_threads(Source.TELEGRAM, OTHER.chat_id, T0 + timedelta(hours=1), [])
    await index.index_threads([threads[3].thread_id, "-1:404"])
    assert await _fts_rows(engine) == 3


async def test_rebuild_reindexes_every_thread(
    repo: SqlRepository, index: Fts5SearchIndex, engine: AsyncEngine
) -> None:
    await _corpus(repo, index)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM threads_fts"))
        await conn.execute(text("INSERT INTO threads_fts VALUES ('ghost', 'x', 'montevideo')"))
    await index.rebuild()
    assert await _fts_rows(engine) == 4
    assert await _hits(index, "montevideo") == ["30"]


async def test_search_on_an_empty_index(index: Fts5SearchIndex) -> None:
    assert await index.search("anything", ANY) == []


def test_needs_sqlite() -> None:
    engine = cast("AsyncEngine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    with pytest.raises(ValueError, match="needs SQLite"):
        Fts5SearchIndex(engine)


async def _fts_rows(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text("SELECT count(*) FROM threads_fts"))).scalar_one())


@pytest.mark.parametrize(
    ("stored", "query"),
    [
        ("\u0441\u0447\u0451\u0442 \u0432 BROU", "\u0441\u0447\u0435\u0442"),  # yo stored, ie typed
        ("\u0441\u0447\u0435\u0442 \u0432 BROU", "\u0441\u0447\u0451\u0442"),  # ie stored, yo typed
        ("\u0401\u041b\u041a\u0410", "\u0435\u043b\u043a\u0430"),  # capital YO
    ],
)
async def test_cyrillic_yo_and_ie_match_each_other(
    repo: SqlRepository, index: Fts5SearchIndex, stored: str, query: str
) -> None:
    message = make_message(40, stored, minutes=0)
    threads = await run_pipeline(repo, [message], noise={}, threads=[[message]])
    await index.index_threads([t.thread_id for t in threads])

    assert await _hits(index, query) == ["40"]
