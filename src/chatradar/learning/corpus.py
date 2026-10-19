"""All generators together: feed messages in, take candidate terms out."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.learning.generators import GratitudeMiner, Miner, QuestionMiner, SpamMiner
from chatradar.learning.verdict import verdict_of

if TYPE_CHECKING:
    from collections.abc import Mapping

    from chatradar.config import LearningSettings
    from chatradar.domain.evaluation import MessageLabel
    from chatradar.domain.lexicon import LexiconTerm
    from chatradar.domain.models import MessageKey, StoredMessage


class CorpusMiner:
    """One pass over the corpus; `terms()` caps every kind at `max_candidates_per_kind`."""

    def __init__(
        self, settings: LearningSettings, labels: Mapping[MessageKey, MessageLabel] | None = None
    ) -> None:
        self._settings = settings
        self._labels: Mapping[MessageKey, MessageLabel] = labels or {}
        self._miners: list[Miner] = [
            GratitudeMiner(settings),
            SpamMiner(settings),
            QuestionMiner(settings),
        ]
        self.messages = 0

    def observe(self, msg: StoredMessage) -> None:
        self.messages += 1
        verdict = verdict_of(msg, self._labels)
        for miner in self._miners:
            miner.observe(msg, verdict)

    def terms(self) -> list[LexiconTerm]:
        """Best-scoring candidates, at most `max_candidates_per_kind` per kind."""
        kept: list[LexiconTerm] = []
        taken: dict[str, int] = {}
        found = sorted(
            (term for miner in self._miners for term in miner.candidates()),
            key=lambda t: (-t.score, -t.occurrences, t.term),
        )
        for term in found:
            if taken.get(term.kind.value, 0) < self._settings.max_candidates_per_kind:
                taken[term.kind.value] = taken.get(term.kind.value, 0) + 1
                kept.append(term)
        return kept
