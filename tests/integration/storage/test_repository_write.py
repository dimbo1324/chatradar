from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from chatradar.domain.models import ChatInfo, ChatKind, Source, SyncState, UpsertResult
from chatradar.pipeline.base import STAGE_ORDER
from tests.integration.storage.helpers import (
    CHAT,
    OTHER,
    T0,
    make_message,
    make_thread,
    result,
    run_pipeline,
)

if TYPE_CHECKING:
    from chatradar.storage.db.repositories import SqlRepository

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------- chats and sync state


async def test_chats_upsert_get_and_list(repo: SqlRepository) -> None:
    await repo.upsert_chats([CHAT, OTHER])
    renamed = CHAT.model_copy(update={"title": "Renamed", "kind": ChatKind.CHANNEL})
    await repo.upsert_chats([renamed])

    assert await repo.get_chat(Source.TELEGRAM, CHAT.chat_id) == renamed
    assert await repo.get_chat(Source.TELEGRAM, "-1") is None
    assert await repo.list_chats() == [renamed, OTHER]


async def test_sync_state_is_replaced(repo: SqlRepository) -> None:
    assert await repo.get_sync_state(Source.TELEGRAM, CHAT.chat_id) is None
    first = SyncState(source=Source.TELEGRAM, chat_id=CHAT.chat_id, last_id="10", last_sync_at=T0)
    second = first.model_copy(update={"last_id": "20", "last_sync_at": T0 + timedelta(hours=1)})
    await repo.set_sync_state(first)
    await repo.set_sync_state(second)

    assert await repo.get_sync_state(Source.TELEGRAM, CHAT.chat_id) == second


# ---------------------------------------------------------------- upsert


async def test_upsert_counts_insert_update_and_unchanged(repo: SqlRepository) -> None:
    first = [make_message(1), make_message(2), make_message(3)]
    assert await repo.upsert_many(first, 1) == UpsertResult(inserted=3)

    edited = make_message(2, "edited text")
    again = [first[0], edited, first[2], make_message(4)]
    assert await repo.upsert_many(again, 1) == UpsertResult(inserted=1, updated=1, unchanged=2)

    stored = await repo.get_many([m.key for m in again])
    assert stored[edited.key].text == "edited text"
    assert stored[edited.key].content_hash == edited.content_hash
    assert {m.versions["normalize"] for m in stored.values()} == {1}


async def test_upsert_of_nothing_is_a_no_op(repo: SqlRepository) -> None:
    assert await repo.upsert_many([], 1) == UpsertResult()


async def test_changed_hash_resets_every_stage_and_its_results(repo: SqlRepository) -> None:
    messages = [make_message(1, "question?"), make_message(2, "answer")]
    await run_pipeline(repo, messages, noise={"2": "short"}, threads=[messages])
    await repo.mark("index", 1, [result(m) for m in messages])

    await repo.upsert_many([make_message(2, "a longer answer now"), messages[0]], 2)
    stored = await repo.get_many([m.key for m in messages])

    untouched, changed = stored[messages[0].key], stored[messages[1].key]
    assert untouched.versions == dict.fromkeys(("normalize", *STAGE_ORDER), 1)
    assert untouched.thread_id is not None
    assert changed.versions == {"normalize": 2}
    assert changed.is_noise is None
    assert changed.noise_reason is None
    assert changed.lang is None
    assert changed.is_question is None
    assert changed.urls == ()
    assert changed.has_mention is None
    assert changed.thread_id is None


async def test_unchanged_hash_keeps_the_stage_results(repo: SqlRepository) -> None:
    message = make_message(1)
    await run_pipeline(repo, [message], noise={"1": "short"})

    assert await repo.upsert_many([message], 5) == UpsertResult(unchanged=1)
    stored = (await repo.get_many([message.key]))[message.key]
    assert stored.versions["normalize"] == 1
    assert stored.is_noise is True


async def test_upsert_handles_batches_bigger_than_one_query(repo: SqlRepository) -> None:
    messages = [make_message(i) for i in range(1, 1201)]
    assert await repo.upsert_many(messages, 1) == UpsertResult(inserted=1200)
    assert await repo.upsert_many(messages, 1) == UpsertResult(unchanged=1200)
    assert len(await repo.get_many([m.key for m in messages])) == 1200


# ---------------------------------------------------------------- pending and mark


async def test_pending_for_respects_versions_dependency_order_and_limit(
    repo: SqlRepository,
) -> None:
    other = make_message(1, chat=OTHER, minutes=0)
    late, early = make_message(2, minutes=50), make_message(3, minutes=10)
    await repo.upsert_many([late, early, other], 1)

    pending = await repo.pending_for("noise", 1, "normalize", 10)
    assert [m.key for m in pending] == [early.key, late.key, other.key]
    assert await repo.pending_for("enrich", 1, "noise", 10) == []
    assert [m.msg_id for m in await repo.pending_for("noise", 1, None, 2)] == ["3", "2"]

    await repo.mark("noise", 1, [result(early, is_noise=False, noise_reason=None)])
    assert [m.key for m in await repo.pending_for("enrich", 1, "noise", 10)] == [early.key]
    assert early.key not in {m.key for m in await repo.pending_for("noise", 1, None, 10)}
    assert early.key in {m.key for m in await repo.pending_for("noise", 2, None, 10)}


async def test_pending_for_rejects_unknown_stage(repo: SqlRepository) -> None:
    with pytest.raises(ValueError, match="unknown stage"):
        await repo.pending_for("text; DROP TABLE messages", 1, None, 10)
    with pytest.raises(ValueError, match="unknown stage"):
        await repo.pending_for("noise", 1, "nope", 10)


async def test_mark_writes_values_version_and_json_urls(repo: SqlRepository) -> None:
    message = make_message(1)
    await repo.upsert_many([message], 1)
    await repo.mark(
        "enrich",
        3,
        [result(message, lang="es", is_question=True, urls=["https://a.test/x"], has_mention=True)],
    )
    stored = (await repo.get_many([message.key]))[message.key]
    assert stored.lang == "es"
    assert stored.is_question is True
    assert stored.urls == ("https://a.test/x",)
    assert stored.has_mention is True
    assert stored.versions == {"normalize": 1, "enrich": 3}


@pytest.mark.parametrize(
    ("stage", "values"),
    [
        ("noise", {"lang": "ru"}),
        ("enrich", {"is_noise": True}),
        ("threads", {"text": "overwritten"}),
        ("index", {"thread_id": "x"}),
        ("noise", {"normalize_v": 9}),
    ],
)
async def test_mark_rejects_columns_of_other_stages(
    repo: SqlRepository, stage: str, values: dict[str, str | bool | int]
) -> None:
    message = make_message(1)
    await repo.upsert_many([message], 1)
    with pytest.raises(ValueError, match="may not write"):
        await repo.mark(stage, 1, [result(message), result(message, **values)])
    stored = (await repo.get_many([message.key]))[message.key]
    assert stored.versions == {"normalize": 1}
    assert stored.text == message.text


async def test_mark_rejects_unknown_stage(repo: SqlRepository) -> None:
    with pytest.raises(ValueError, match="unknown pipeline stage"):
        await repo.mark("normalize", 1, [])


async def test_mark_resets_later_stages_only_for_marked_messages(repo: SqlRepository) -> None:
    first, second = make_message(1), make_message(2)
    await run_pipeline(repo, [first, second], threads=[[first, second]])

    await repo.mark("noise", 2, [result(first, is_noise=True, noise_reason="spam")])
    stored = await repo.get_many([first.key, second.key])

    assert stored[first.key].versions == {"normalize": 1, "noise": 2}
    assert stored[first.key].is_noise is True
    assert stored[second.key].versions == {"normalize": 1, "noise": 1, "enrich": 1, "threads": 1}


async def test_mark_with_mixed_value_sets_in_one_call(repo: SqlRepository) -> None:
    first, second = make_message(1), make_message(2)
    await repo.upsert_many([first, second], 1)
    await repo.mark(
        "noise", 1, [result(first, is_noise=False), result(second, is_noise=True, noise_reason="x")]
    )
    stored = await repo.get_many([first.key, second.key])
    assert (stored[first.key].is_noise, stored[first.key].noise_reason) == (False, None)
    assert (stored[second.key].is_noise, stored[second.key].noise_reason) == (True, "x")


async def test_mark_rejects_non_list_urls(repo: SqlRepository) -> None:
    message = make_message(1)
    await repo.upsert_many([message], 1)
    with pytest.raises(TypeError, match="urls"):
        await repo.mark("enrich", 1, [result(message, urls="https://a.test")])


# ---------------------------------------------------------------- reads used by stages


async def test_get_many_returns_only_known_keys(repo: SqlRepository) -> None:
    message = make_message(1)
    await repo.upsert_many([message], 1)
    missing = make_message(2).key
    assert set(await repo.get_many([message.key, missing, message.key])) == {message.key}
    assert await repo.get_many([]) == {}


async def test_chat_window_is_one_chat_from_since_in_order(repo: SqlRepository) -> None:
    messages = [
        make_message(1, minutes=0),
        make_message(3, minutes=30),
        make_message(2, minutes=30),
        make_message(4, minutes=60),
        make_message(5, chat=OTHER, minutes=40),
    ]
    await repo.upsert_many(messages, 1)

    window = await repo.chat_window(Source.TELEGRAM, CHAT.chat_id, T0 + timedelta(minutes=30))
    assert [m.msg_id for m in window] == ["2", "3", "4"]


async def test_save_threads_replaces_threads_from_since(repo: SqlRepository) -> None:
    old = [make_message(1, minutes=0)]
    tail = [make_message(10, minutes=100), make_message(11, minutes=110)]
    other = [make_message(20, chat=OTHER, minutes=100)]
    await repo.upsert_many([*old, *tail, *other], 1)
    since = T0 + timedelta(minutes=90)

    await repo.save_threads(Source.TELEGRAM, CHAT.chat_id, T0, [make_thread(old[0], old)])
    await repo.save_threads(Source.TELEGRAM, CHAT.chat_id, since, [make_thread(tail[0], tail[:1])])
    await repo.save_threads(Source.TELEGRAM, OTHER.chat_id, since, [make_thread(other[0], other)])
    regrouped = [make_thread(tail[0], tail[:1]), make_thread(tail[1], tail[1:])]
    await repo.save_threads(Source.TELEGRAM, CHAT.chat_id, since, regrouped)

    summaries = {s.chat.chat_id: s.thread_count for s in await repo.chat_summaries()}
    assert summaries == {CHAT.chat_id: 3, OTHER.chat_id: 1}
    assert await repo.get_thread(f"{CHAT.chat_id}:1") is not None
    assert await repo.get_thread(f"{CHAT.chat_id}:11") is not None

    await repo.save_threads(Source.TELEGRAM, CHAT.chat_id, since, [])
    assert await repo.get_thread(f"{CHAT.chat_id}:11") is None
    assert await repo.get_thread(f"{CHAT.chat_id}:1") is not None
    assert await repo.get_thread(f"{OTHER.chat_id}:20") is not None


async def test_save_threads_refuses_threads_of_another_chat(repo: SqlRepository) -> None:
    foreign = make_message(1, chat=OTHER)
    with pytest.raises(ValueError, match="not in chat"):
        await repo.save_threads(
            Source.TELEGRAM, CHAT.chat_id, T0, [make_thread(foreign, [foreign])]
        )


async def test_save_threads_updates_a_thread_that_started_before_since(
    repo: SqlRepository,
) -> None:
    root, later = make_message(1, minutes=0), make_message(2, minutes=200)
    await repo.upsert_many([root, later], 1)
    await repo.save_threads(Source.TELEGRAM, CHAT.chat_id, T0, [make_thread(root, [root])])
    grown = make_thread(root, [root, later])
    await repo.save_threads(Source.TELEGRAM, CHAT.chat_id, T0 + timedelta(minutes=100), [grown])

    detail = await repo.get_thread(grown.thread_id)
    assert detail is not None
    assert detail.thread == grown


async def test_reset_stage_clears_it_and_later_stages(repo: SqlRepository) -> None:
    messages = [make_message(1), make_message(2), make_message(3)]
    await run_pipeline(repo, messages, threads=[messages])
    await repo.upsert_many([make_message(4)], 1)

    assert await repo.reset_stage("enrich") == 3
    stored = await repo.get_many([m.key for m in messages])
    assert {tuple(sorted(m.versions)) for m in stored.values()} == {("noise", "normalize")}
    assert await repo.reset_stage("enrich") == 0
    assert await repo.reset_stage("noise") == 3
    with pytest.raises(ValueError, match="unknown pipeline stage"):
        await repo.reset_stage("normalize")


async def test_unknown_chats_get_placeholder_summaries(repo: SqlRepository) -> None:
    await repo.upsert_many([make_message(1, chat=OTHER)], 1)
    [summary] = await repo.chat_summaries()
    assert summary.chat == ChatInfo(source=Source.TELEGRAM, chat_id=OTHER.chat_id, title="-100600")
