"""Use case: put the built-in word lists into the lexicon table on first start."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.logs import get_logger
from chatradar.pipeline.lexicon import seed_terms

if TYPE_CHECKING:
    from chatradar.domain.ports import LexiconRepository

log = get_logger(__name__)


async def ensure_seeded(repo: LexiconRepository) -> int:
    """Insert seed terms that are missing; terms already there (any status) are untouched,
    so a rejected seed term stays rejected. Returns how many were inserted."""
    inserted = await repo.seed(seed_terms())
    if inserted:
        log.info("lexicon.seeded", inserted=inserted)
    return inserted
