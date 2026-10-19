from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from chatradar.pipeline.base import STAGE_ORDER
from chatradar.pipeline.noise import NoiseStage
from chatradar.pipeline.registry import default_stages, stage_versions
from chatradar.pipeline.runner import run_pipeline
from chatradar.services.process import process
from tests.unit.pipeline.fakes import CHAT_ID, make_deps, make_message

if TYPE_CHECKING:
    from chatradar.domain.models import StoredMessage

ALL_DONE = dict.fromkeys(STAGE_ORDER, 1)


def _chat() -> list[StoredMessage]:
    return [
        make_message(1, "Where can I renew my residence card in Montevideo?", minutes=0),
        make_message(2, "At the migration office on Misiones street", minutes=3, reply_to=1),
        make_message(3, "Thanks!", minutes=4, reply_to=2),
        make_message(4, "Anyone selling a used heater for the winter?", minutes=300),
        make_message(5, "ok", minutes=301),
    ]


class NoiseV2(NoiseStage):
    version = 2


async def test_full_run_then_nothing_left() -> None:
    deps, repo, search = make_deps(_chat())

    first = await run_pipeline(default_stages(), deps, batch_size=2)
    second = await run_pipeline(default_stages(), deps, batch_size=2)

    assert first == dict.fromkeys(STAGE_ORDER, 5)
    assert second == dict.fromkeys(STAGE_ORDER, 0)
    assert repo.row(3).noise_reason == "gratitude"
    assert repo.row(5).noise_reason == "short"
    assert {repo.row(i).thread_id for i in (1, 2)} == {f"{CHAT_ID}:1"}
    assert repo.row(3).thread_id is None
    assert repo.row(4).thread_id == f"{CHAT_ID}:4"
    assert set(search.entries) == {f"{CHAT_ID}:1", f"{CHAT_ID}:4"}
    assert "Thanks" not in search.entries[f"{CHAT_ID}:1"]
    assert all(m.versions == ALL_DONE for m in repo.rows.values())


async def test_version_bump_reprocesses_that_stage_and_every_later_one() -> None:
    deps, repo, _ = make_deps(_chat())
    await run_pipeline(default_stages(), deps)
    stages = default_stages()
    stages[0] = NoiseV2()

    counts = await run_pipeline(stages, deps)

    assert counts == dict.fromkeys(STAGE_ORDER, 5)
    assert all(m.versions == {**ALL_DONE, "noise": 2} for m in repo.rows.values())
    assert await run_pipeline(stages, deps) == dict.fromkeys(STAGE_ORDER, 0)


async def test_new_messages_flow_through_every_stage() -> None:
    deps, repo, search = make_deps(_chat())
    await run_pipeline(default_stages(), deps)
    repo.add(make_message(6, "The office also takes appointments online", minutes=6, reply_to=1))

    counts = await run_pipeline(default_stages(), deps)

    assert counts["noise"] == counts["enrich"] == 1
    assert counts["threads"] == 6, "the whole two-day window is regrouped"
    assert repo.row(6).thread_id == f"{CHAT_ID}:1"
    assert "appointments online" in search.entries[f"{CHAT_ID}:1"]


async def test_index_drops_a_thread_that_was_merged_away() -> None:
    deps, repo, search = make_deps(
        [
            make_message(1, "Which bank opens accounts for new residents quickly", minutes=0),
            make_message(3, "Mine took two weeks at the bank in Ciudad Vieja", minutes=40),
        ]
    )
    await run_pipeline(default_stages(), deps)
    assert set(search.entries) == {f"{CHAT_ID}:1", f"{CHAT_ID}:3"}
    repo.add(make_message(2, "I asked the same thing last month at the bank", minutes=20))

    await run_pipeline(default_stages(), deps)

    assert set(search.entries) == {f"{CHAT_ID}:1"}
    assert "Ciudad Vieja" in search.entries[f"{CHAT_ID}:1"]


async def test_only_runs_one_stage() -> None:
    deps, repo, _ = make_deps(_chat())

    assert await run_pipeline(default_stages(), deps, only="noise") == {"noise": 5}
    assert all(m.versions == {"noise": 1} for m in repo.rows.values())


async def test_unknown_stage_and_bad_batch_size_are_rejected() -> None:
    deps, _, _ = make_deps()
    with pytest.raises(ValueError, match="unknown stage"):
        await run_pipeline(default_stages(), deps, only="embeddings")
    with pytest.raises(ValueError, match="batch_size"):
        await run_pipeline(default_stages(), deps, batch_size=0)


async def test_logs_one_event_per_stage() -> None:
    deps, _, _ = make_deps(_chat())
    with capture_logs() as events:
        await run_pipeline(default_stages(), deps)

    done = [e for e in events if e["event"] == "pipeline.stage_done"]
    assert [e["stage"] for e in done] == list(STAGE_ORDER)
    assert all(e["count"] == 5 and isinstance(e["duration_ms"], int) for e in done)


async def test_process_resets_a_stage_first() -> None:
    deps, repo, _ = make_deps(_chat())
    await process(deps)

    counts = await process(deps, reset="threads", batch_size=3)

    assert counts == {"noise": 0, "enrich": 0, "threads": 5, "index": 5}
    assert all(m.versions == ALL_DONE for m in repo.rows.values())


async def test_process_rejects_an_unknown_reset() -> None:
    deps, _, _ = make_deps()
    with pytest.raises(ValueError, match="unknown stage"):
        await process(deps, reset="normalize")


def test_registry_follows_stage_order() -> None:
    stages = default_stages()
    assert [s.name for s in stages] == list(STAGE_ORDER)
    assert [s.depends_on for s in stages] == [None, "noise", "enrich", "threads"]
    assert stage_versions() == [(s.name, s.version) for s in stages]
