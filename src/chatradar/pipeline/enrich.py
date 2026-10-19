"""Stage `enrich`: cheap features of useful messages, without AI.

`lang` (`ru`, `es`, `en`, `mixed`, `unknown`), `is_question`, `urls` and `has_mention`.
Noise messages get empty values but are still marked done. Phone numbers and other
personal data are never extracted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.domain.models import StageResult
from chatradar.pipeline.features import (
    detect_language,
    extract_urls,
    has_mention,
    looks_like_question,
)

if TYPE_CHECKING:
    from chatradar.domain.models import ResultValue, StoredMessage
    from chatradar.pipeline.base import StageDeps

ENRICH_VERSION = 1


def features(msg: StoredMessage) -> dict[str, ResultValue]:
    if msg.is_noise:
        return {"lang": None, "is_question": None, "urls": [], "has_mention": None}
    return {
        "lang": detect_language(msg.text),
        "is_question": looks_like_question(msg.text),
        "urls": extract_urls(msg.text),
        "has_mention": has_mention(msg.text),
    }


class EnrichStage:
    name = "enrich"
    version = ENRICH_VERSION
    depends_on: str | None = "noise"

    async def run(self, deps: StageDeps, limit: int) -> int:
        pending = await deps.messages.pending_for(self.name, self.version, self.depends_on, limit)
        if not pending:
            return 0
        results = [StageResult(key=msg.key, values=features(msg)) for msg in pending]
        await deps.messages.mark(self.name, self.version, results)
        return len(results)
