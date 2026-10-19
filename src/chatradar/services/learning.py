"""Mining lexicon candidates from the corpus (statistics only, no AI).

The statistics live in `chatradar.learning` (see its docstring for the memory behavior and
the no-stemming limitation). This module is the I/O around them: stream the corpus, run the
generators, hand the candidates to the lexicon, put long-unseen mined terms to sleep.

Mining never changes the lexicon's active set: it inserts CANDIDATE terms and refreshes the
statistics (including `last_seen`) of existing ones; a human decides what becomes active.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING

from chatradar.domain.lexicon import LexiconKind, MiningReport, TermSource
from chatradar.learning.corpus import CorpusMiner

if TYPE_CHECKING:
    from datetime import datetime

    from chatradar.config import LearningSettings
    from chatradar.domain.lexicon import LexiconTerm
    from chatradar.domain.ports import LabelRepository, LexiconRepository, MessageScanner


async def mine_candidates(
    settings: LearningSettings,
    *,
    scanner: MessageScanner,
    lexicon: LexiconRepository,
    labels: LabelRepository,
    now: datetime,
) -> MiningReport:
    """Scan the corpus, score phrases, record candidates, and put long-unseen mined terms
    to sleep (`settings.dormant_after_days`). Human labels override the filter's own
    verdicts when they are used as the class of a message."""
    started = time.monotonic()
    miner = CorpusMiner(settings, {label.key: label for label in await labels.list_labels()})
    async for batch in scanner.iter_all():
        for msg in batch:
            miner.observe(msg)

    by_kind: dict[LexiconKind, list[LexiconTerm]] = {}
    for term in miner.terms():
        by_kind.setdefault(term.kind, []).append(await _align_language(lexicon, term))

    new_by_kind: dict[str, int] = {}
    inserted_total = refreshed_total = 0
    for kind in LexiconKind:
        terms = by_kind.get(kind)
        if not terms:
            continue
        inserted, refreshed = await lexicon.upsert_candidates(terms)
        inserted_total += inserted
        refreshed_total += refreshed
        if inserted:
            new_by_kind[kind.value] = inserted

    dormant = await lexicon.mark_dormant(
        last_seen_before=now - timedelta(days=settings.dormant_after_days),
        sources=[TermSource.STATS],
    )
    return MiningReport(
        messages=miner.messages,
        new_candidates=inserted_total,
        refreshed=refreshed_total,
        dormant=dormant,
        by_kind=new_by_kind,
        duration_ms=round((time.monotonic() - started) * 1000),
    )


async def _align_language(lexicon: LexiconRepository, term: LexiconTerm) -> LexiconTerm:
    """A term that already exists as language-neutral (a seed, say) is refreshed under `any`
    instead of being proposed a second time under the language it happens to be written in."""
    if term.lang == "any":
        return term
    if await lexicon.get_term(term.kind, "any", term.term) is not None:
        return term.model_copy(update={"lang": "any"})
    return term
