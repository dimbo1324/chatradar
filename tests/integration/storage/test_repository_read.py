from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from chatradar.domain.models import (
    MessageFilter,
    PipelineStats,
    Source,
    StageStat,
    SyncState,
)
from tests.integration.storage.helpers import (
    CHAT,
    OTHER,
    T0,
    make_message,
    result,
    run_pipeline,
)

if TYPE_CHECKING:
    from chatradar.storage.db.repositories import SqlRepository

pytestmark = pytest.mark.integration


async def _corpus(repo: SqlRepository) -> None:
    """Chat CHAT: 1 (question, root) ← 2, noise 3 (reason "short"), 4 (spam);
    chat OTHER: 5 (question, root) ← 6, unprocessed 7. Re-marking enrich for 5 makes
    it Spanish and resets its threads version."""
    await repo.upsert_chats([CHAT, OTHER])
    first = [
        make_message(1, "how do I renew a cedula?", minutes=0),
        make_message(2, "at the office", minutes=5, reply_to=1),
        make_message(3, "ok", minutes=6),
        make_message(4, "earn money fast", minutes=7),
    ]
    second = [
        make_message(5, "where to buy a bike?", chat=OTHER, minutes=60),
        make_message(6, "at the market", chat=OTHER, minutes=61, reply_to=5),
    ]
    await run_pipeline(
        repo,
        [*first, *second],
        noise={"3": "short", "4": "spam"},
        threads=[first[:2], second],
    )
    await repo.mark("enrich", 1, [result(second[0], lang="es", is_question=True, urls=[])])
    await repo.upsert_many([make_message(7, chat=OTHER, minutes=120)], 1)


async def test_chat_summaries_count_messages_noise_threads_and_dates(
    repo: SqlRepository,
) -> None:
    await _corpus(repo)
    await repo.set_sync_state(
        SyncState(source=Source.TELEGRAM, chat_id=CHAT.chat_id, last_id="4", last_sync_at=T0)
    )
    first, second = await repo.chat_summaries()

    assert first.chat == CHAT
    assert (first.message_count, first.noise_count, first.thread_count) == (4, 2, 1)
    assert first.first_message_at == T0
    assert first.last_message_at == T0 + timedelta(minutes=7)
    assert first.last_sync_at == T0
    assert second.chat == OTHER
    assert (second.message_count, second.noise_count, second.thread_count) == (3, 0, 1)
    assert second.last_message_at == T0 + timedelta(minutes=120)
    assert second.last_sync_at is None


async def test_chat_summaries_of_an_empty_chat(repo: SqlRepository) -> None:
    await repo.upsert_chats([CHAT])
    [summary] = await repo.chat_summaries()
    assert (summary.message_count, summary.noise_count, summary.thread_count) == (0, 0, 0)
    assert summary.first_message_at is None


async def test_pipeline_stats_done_and_pending_per_version(repo: SqlRepository) -> None:
    await _corpus(repo)
    stats = await repo.pipeline_stats([("noise", 1), ("enrich", 2), ("threads", 1), ("index", 1)])
    assert stats == PipelineStats(
        total_messages=7,
        stages=[
            StageStat(stage="noise", version=1, done=6, pending=1),
            StageStat(stage="enrich", version=2, done=0, pending=7),
            StageStat(stage="threads", version=1, done=3, pending=4),
            StageStat(stage="index", version=1, done=0, pending=7),
        ],
    )


async def test_pipeline_stats_of_an_empty_database(repo: SqlRepository) -> None:
    stats = await repo.pipeline_stats([("noise", 1)])
    assert stats.total_messages == 0
    assert stats.stages == [StageStat(stage="noise", version=1, done=0, pending=0)]


async def test_pipeline_stats_rejects_unknown_stage(repo: SqlRepository) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        await repo.pipeline_stats([("bogus", 1)])


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (MessageFilter(), ["7", "6", "5", "4", "3", "2", "1"]),
        (MessageFilter(source=Source.TELEGRAM, chat_id=CHAT.chat_id), ["4", "3", "2", "1"]),
        (MessageFilter(source=Source.WHATSAPP), []),
        (MessageFilter(chat_id=OTHER.chat_id), ["7", "6", "5"]),
        (MessageFilter(date_from=T0 + timedelta(minutes=6)), ["7", "6", "5", "4", "3"]),
        (MessageFilter(date_to=T0 + timedelta(minutes=5)), ["2", "1"]),
        (
            MessageFilter(date_from=T0 + timedelta(minutes=5), date_to=T0 + timedelta(minutes=60)),
            ["5", "4", "3", "2"],
        ),
        (MessageFilter(lang="es"), ["5"]),
        (MessageFilter(lang="ru"), ["6", "4", "3", "2", "1"]),
        (MessageFilter(is_noise=True), ["4", "3"]),
        (MessageFilter(is_noise=False), ["6", "5", "2", "1"]),
        (MessageFilter(noise_reason="spam"), ["4"]),
        (MessageFilter(is_question=True), ["5", "1"]),
        (MessageFilter(is_question=False), ["6", "4", "3", "2"]),
        (MessageFilter(thread_id=f"{CHAT.chat_id}:1"), ["2", "1"]),
        (MessageFilter(chat_id=CHAT.chat_id, is_noise=False, is_question=False), ["2"]),
    ],
)
async def test_list_messages_filters_newest_first(
    repo: SqlRepository, filters: MessageFilter, expected: list[str]
) -> None:
    await _corpus(repo)
    page = await repo.list_messages(filters)
    assert [m.msg_id for m in page.items] == expected
    assert page.total == len(expected)


async def test_list_messages_pages_with_total(repo: SqlRepository) -> None:
    await _corpus(repo)
    page = await repo.list_messages(MessageFilter(limit=3, offset=2))
    assert [m.msg_id for m in page.items] == ["5", "4", "3"]
    assert (page.total, page.limit, page.offset) == (7, 3, 2)
    beyond = await repo.list_messages(MessageFilter(limit=3, offset=7))
    assert beyond.items == []
    assert beyond.total == 7


async def test_get_thread_returns_its_messages_chronologically(repo: SqlRepository) -> None:
    await _corpus(repo)
    detail = await repo.get_thread(f"{CHAT.chat_id}:1")
    assert detail is not None
    assert detail.thread.msg_count == 2
    assert detail.thread.started_at == T0
    assert [m.msg_id for m in detail.messages] == ["1", "2"]
    assert await repo.get_thread("-1:1") is None


async def test_get_thread_leaves_out_noise(repo: SqlRepository) -> None:
    root, noisy = make_message(1), make_message(2, "+1")
    await run_pipeline(repo, [root, noisy], noise={"2": "gratitude"}, threads=[[root, noisy]])
    detail = await repo.get_thread(f"{CHAT.chat_id}:1")
    assert detail is not None
    assert [m.msg_id for m in detail.messages] == ["1"]


async def test_sample_takes_only_the_requested_side(repo: SqlRepository) -> None:
    await _corpus(repo)
    noise = await repo.sample(is_noise=True, n=10)
    clean = await repo.sample(is_noise=False, n=10)
    assert sorted(m.msg_id for m in noise) == ["3", "4"]
    assert sorted(m.msg_id for m in clean) == ["1", "2", "5", "6"]
    assert len(await repo.sample(is_noise=False, n=2)) == 2


async def test_sample_is_random(repo: SqlRepository) -> None:
    messages = [make_message(i) for i in range(1, 41)]
    await run_pipeline(repo, messages)
    orders = {tuple(m.msg_id for m in await repo.sample(is_noise=False, n=40)) for _ in range(5)}
    assert len(orders) > 1


async def test_noise_reasons_count_by_reason(repo: SqlRepository) -> None:
    await _corpus(repo)
    await repo.upsert_many([make_message(8, "+"), make_message(9, "+")], 1)
    await repo.mark(
        "noise",
        1,
        [
            result(make_message(8, "+"), is_noise=True, noise_reason="spam"),
            result(make_message(9, "+"), is_noise=True, noise_reason="spam"),
        ],
    )
    reasons = await repo.noise_reasons()
    assert reasons == {"spam": 3, "short": 1}
    assert list(reasons) == ["spam", "short"]
