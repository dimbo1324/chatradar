"""The pipeline stage contract.

Ingestion maps raw records to messages and upserts them (`normalize_v`). After that the
stages in `STAGE_ORDER` run. Every stage is idempotent and versioned: changed rules →
`version += 1` → only messages with `<stage>_v IS NULL OR < version` are processed again,
and `MessageRepository.mark` resets every later stage for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from chatradar.domain.ports import LexiconRepository, MessageRepository, SearchIndex

NORMALIZE_VERSION = 1
"""Bump when a mapper changes what it produces; `chatradar rebuild` re-maps everything."""

STAGE_ORDER: tuple[str, ...] = ("noise", "enrich", "threads", "index")

STAGE_COLUMNS: dict[str, tuple[str, ...]] = {
    "noise": ("is_noise", "noise_reason"),
    "enrich": ("lang", "is_question", "urls", "has_mention"),
    "threads": ("thread_id",),
    "index": (),
}
"""The only message columns each stage may write through `MessageRepository.mark`."""

VERSION_COLUMNS: tuple[str, ...] = ("normalize_v", *(f"{stage}_v" for stage in STAGE_ORDER))


def later_stages(stage: str) -> tuple[str, ...]:
    """Stages after `stage` in `STAGE_ORDER`; every stage is later than `normalize`."""
    if stage == "normalize":
        return STAGE_ORDER
    return STAGE_ORDER[STAGE_ORDER.index(stage) + 1 :]


@dataclass(frozen=True)
class StageDeps:
    messages: MessageRepository
    search: SearchIndex
    lexicon: LexiconRepository | None = None  # None → the built-in seed lexicon (tests)


class Stage(Protocol):
    name: str  # one of STAGE_ORDER
    version: int
    depends_on: str | None  # the previous stage, None for the first

    async def run(self, deps: StageDeps, limit: int) -> int:
        """Process up to `limit` pending messages through the ports; return how many were
        processed. 0 means nothing is pending."""
        ...
