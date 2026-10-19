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

    mined = miner.terms()
    known = await _known_languages(lexicon, {term.kind for term in mined})
    by_kind: dict[LexiconKind, list[LexiconTerm]] = {}
    for term in mined:
        by_kind.setdefault(term.kind, []).append(_align_language(known, term))

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


_PAGE = 500


async def _known_languages(
    lexicon: LexiconRepository, kinds: set[LexiconKind]
) -> dict[tuple[LexiconKind, str], list[str]]:
    """Every (kind, term) already in the lexicon, with the languages it exists under."""
    known: dict[tuple[LexiconKind, str], list[str]] = {}
    for kind in kinds:
        offset = 0
        while True:
            page = await lexicon.list_terms(kind=kind, limit=_PAGE, offset=offset)
            for existing in page.items:
                known.setdefault((existing.kind, existing.term), []).append(existing.lang)
            offset += _PAGE
            if offset >= page.total:
                break
    return known


def _align_language(
    known: dict[tuple[LexiconKind, str], list[str]], term: LexiconTerm
) -> LexiconTerm:
    """A phrase that already exists, under any language, is refreshed there instead of being
    proposed again under the language it happens to be written in (a Russian "thanks" seeded as
    `ru` but mined as `any`, say). An exact language match wins, then `any`, then the first."""
    languages = known.get((term.kind, term.term))
    if not languages or term.lang in languages:
        return term
    chosen = "any" if "any" in languages else languages[0]
    return term.model_copy(update={"lang": chosen})
