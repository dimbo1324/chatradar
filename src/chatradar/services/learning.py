"""Mining lexicon candidates from the corpus (statistics only, no AI).

Contract written by the lead; package B replaces the body. Mining never changes the
lexicon's active set: it inserts CANDIDATE terms and refreshes statistics (including
`last_seen` of active mined terms); a human decides what becomes active.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from chatradar.config import LearningSettings
    from chatradar.domain.lexicon import MiningReport
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
    raise NotImplementedError
