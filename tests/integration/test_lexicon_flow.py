"""The learning loop on real adapters: import → process → decide → process again."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from chatradar.config import Settings
from chatradar.domain.lexicon import (
    LexiconKind,
    LexiconTerm,
    TermDecision,
    TermSource,
    TermStatus,
)
from chatradar.domain.models import MessageFilter
from chatradar.services.container import open_runtime
from chatradar.services.ingest import import_tg_export
from chatradar.services.process import process

if TYPE_CHECKING:
    from chatradar.services.container import Runtime

pytestmark = pytest.mark.integration

EXPORT = Path(__file__).parents[1] / "fixtures" / "synthetic" / "en_expats.json"
CANDIDATE = "good morning all"  # a whole 16-character message, not in the seed
SEEDED = "thanks for sharing"  # a whole 18-character message, in the seed


def _texts(needle: str) -> int:
    data = json.loads(EXPORT.read_text(encoding="utf-8"))
    return sum(
        1
        for m in data["messages"]
        if isinstance(m.get("text"), str) and needle == m["text"].lower()
    )


async def _noise_reasons(rt: Runtime, text: str) -> list[str | None]:
    page = await rt.read.messages(MessageFilter(limit=500))
    return [m.noise_reason for m in page.items if m.text.lower() == text]


async def _import(rt: Runtime) -> None:
    await import_tg_export(
        EXPORT, username="demo", raw=rt.raw, chats=rt.repo, messages=rt.repo, catalog=rt.raw
    )


async def test_accepted_candidate_and_rejected_seed_term_change_the_noise(
    tmp_path: Path,
) -> None:
    candidate_count = _texts(CANDIDATE)
    seeded_count = _texts(SEEDED)
    assert candidate_count > 0
    assert seeded_count > 0

    async with open_runtime(Settings(data_dir=tmp_path / "data")) as rt:
        await _import(rt)
        await process(rt.stage_deps)
        assert await _noise_reasons(rt, CANDIDATE) == [None] * candidate_count
        assert await _noise_reasons(rt, SEEDED) == ["gratitude"] * seeded_count
        summary = await rt.lexicon.summary()
        assert summary.applied == {"noise": summary.revision, "enrich": summary.revision}
        assert not summary.pending_apply

        await rt.lexicon.upsert_candidates(
            [LexiconTerm(kind=LexiconKind.GRATITUDE, term=CANDIDATE, source=TermSource.STATS)]
        )
        again = await process(rt.stage_deps)
        assert again["noise"] == 0

        await rt.feedback.decide_term(LexiconKind.GRATITUDE, "any", CANDIDATE, TermDecision.ACCEPT)
        assert (await rt.lexicon.summary()).pending_apply
        await process(rt.stage_deps)
        assert await _noise_reasons(rt, CANDIDATE) == ["gratitude"] * candidate_count
        assert await _noise_reasons(rt, SEEDED) == ["gratitude"] * seeded_count
        assert not (await rt.lexicon.summary()).pending_apply

        seeded = next(
            t
            for t in (await rt.lexicon.list_terms(kind=LexiconKind.GRATITUDE, limit=500)).items
            if t.term.lower() == SEEDED
        )
        assert seeded.status is TermStatus.ACTIVE
        await rt.feedback.decide_term(
            LexiconKind.GRATITUDE, seeded.lang, seeded.term, TermDecision.REJECT
        )
        await process(rt.stage_deps)
        assert await _noise_reasons(rt, SEEDED) == [None] * seeded_count
        assert await _noise_reasons(rt, CANDIDATE) == ["gratitude"] * candidate_count

        quiet = await process(rt.stage_deps)
        assert quiet["noise"] == 0


async def test_a_restart_keeps_decisions_and_does_not_reseed_over_them(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    async with open_runtime(settings) as rt:
        await rt.lexicon.decide(
            LexiconKind.GRATITUDE, "en", "thanks", TermDecision.REJECT, by="human"
        )
        revision = await rt.lexicon.revision()

    async with open_runtime(settings) as rt:
        assert await rt.lexicon.revision() == revision
        thanks = await rt.lexicon.get_term(LexiconKind.GRATITUDE, "en", "thanks")
        assert thanks is not None
        assert thanks.status is TermStatus.REJECTED
