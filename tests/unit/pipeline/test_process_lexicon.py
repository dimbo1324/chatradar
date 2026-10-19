from __future__ import annotations

import pytest

from chatradar.domain.lexicon import LexiconSnapshot
from chatradar.pipeline.base import StageDeps
from chatradar.services.process import process
from tests.unit.pipeline.fakes import FakeMessages, FakeSearch, make_deps, make_message


class FakeLexicon:
    """Only what `process` and the stages use: revision, snapshot, applied revisions."""

    def __init__(self, revision: int = 1) -> None:
        self.current = revision
        self.applied: dict[str, int] = {}
        self.calls: list[tuple[str, str, int]] = []

    async def revision(self) -> int:
        return self.current

    async def snapshot(self) -> LexiconSnapshot:
        return LexiconSnapshot(revision=self.current, entries={"gratitude": ("thanks",)})

    async def applied_revision(self, stage: str) -> int:
        return self.applied.get(stage, 0)

    async def set_applied_revision(self, stage: str, revision: int) -> None:
        self.applied[stage] = revision
        self.calls.append(("set", stage, revision))


class SpyMessages(FakeMessages):
    def __init__(self) -> None:
        super().__init__()
        self.resets: list[str] = []

    async def reset_stage(self, stage: str) -> int:
        self.resets.append(stage)
        return await super().reset_stage(stage)


def _setup(revision: int) -> tuple[StageDeps, SpyMessages, FakeLexicon]:
    repo = SpyMessages()
    repo.add(make_message(1, "Is the office open on Monday?"), make_message(2, "thanks"))
    lexicon = FakeLexicon(revision)
    deps = StageDeps(messages=repo, search=FakeSearch(repo), lexicon=lexicon)  # type: ignore[arg-type]
    return deps, repo, lexicon


async def test_first_run_marks_both_stages_and_resets_stale_noise_once() -> None:
    deps, repo, lexicon = _setup(revision=1)

    await process(deps)

    assert repo.resets == ["noise"]
    assert lexicon.applied == {"noise": 1, "enrich": 1}


async def test_nothing_is_reset_when_the_revision_is_applied() -> None:
    deps, repo, lexicon = _setup(revision=3)
    lexicon.applied = {"noise": 3, "enrich": 3}

    counts = await process(deps)

    assert repo.resets == []
    assert lexicon.applied == {"noise": 3, "enrich": 3}
    assert counts["noise"] == 2


async def test_only_the_stale_enrich_is_reset_when_noise_is_current() -> None:
    deps, repo, lexicon = _setup(revision=4)
    lexicon.applied = {"noise": 4, "enrich": 2}

    await process(deps)

    assert repo.resets == ["enrich"]
    assert lexicon.applied == {"noise": 4, "enrich": 4}


async def test_stale_noise_resets_noise_only_because_it_cascades() -> None:
    deps, repo, lexicon = _setup(revision=5)
    lexicon.applied = {"noise": 1, "enrich": 1}

    await process(deps)

    assert repo.resets == ["noise"]
    assert lexicon.applied == {"noise": 5, "enrich": 5}


async def test_a_decision_during_the_run_leaves_the_stages_behind() -> None:
    deps, _, lexicon = _setup(revision=2)
    original = lexicon.snapshot

    async def moving_snapshot() -> LexiconSnapshot:
        lexicon.current = 3
        return await original()

    lexicon.snapshot = moving_snapshot  # type: ignore[method-assign]

    await process(deps)

    assert lexicon.applied == {"noise": 2, "enrich": 2}
    assert await lexicon.revision() == 3


async def test_explicit_reset_is_not_repeated_for_stale_stages() -> None:
    deps, repo, _ = _setup(revision=1)

    await process(deps, reset="noise")

    assert repo.resets == ["noise"]


async def test_explicit_reset_of_a_later_stage_still_resets_stale_noise() -> None:
    deps, repo, _ = _setup(revision=1)

    await process(deps, reset="enrich")

    assert repo.resets == ["enrich", "noise"]


async def test_only_a_non_lexicon_stage_leaves_the_revision_alone() -> None:
    deps, repo, lexicon = _setup(revision=1)

    await process(deps, only="threads")

    assert repo.resets == []
    assert lexicon.calls == []


async def test_only_enrich_marks_enrich_alone() -> None:
    deps, repo, lexicon = _setup(revision=2)

    await process(deps, only="enrich")

    assert repo.resets == ["enrich"]
    assert lexicon.applied == {"enrich": 2}


async def test_unknown_reset_is_rejected() -> None:
    deps, _, _ = _setup(revision=1)

    with pytest.raises(ValueError, match="unknown stage"):
        await process(deps, reset="nope")


async def test_without_a_lexicon_nothing_is_tracked() -> None:
    deps, repo, _ = make_deps([make_message(1, "thanks")])

    await process(deps)

    assert isinstance(repo, FakeMessages)
    assert repo.row(1).is_noise is True
