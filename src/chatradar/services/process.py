"""Use case: run the pipeline over everything pending, optionally after a reset."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.domain.lexicon import STAGE_LEXICON_KINDS
from chatradar.logs import get_logger
from chatradar.pipeline.base import STAGE_ORDER
from chatradar.pipeline.registry import default_stages
from chatradar.pipeline.runner import run_pipeline

if TYPE_CHECKING:
    from chatradar.domain.ports import LexiconRepository, MessageRepository
    from chatradar.pipeline.base import StageDeps

log = get_logger(__name__)

_LEXICON_STAGES: tuple[str, ...] = tuple(s for s in STAGE_ORDER if s in STAGE_LEXICON_KINDS)


async def process(
    deps: StageDeps,
    *,
    only: str | None = None,
    reset: str | None = None,
    batch_size: int = 500,
) -> dict[str, int]:
    """`reset` clears a stage (and every later one) so it reprocesses all messages.

    With a lexicon in `deps`, the stages that read it (`noise`, `enrich`) remember the
    revision they processed with. A stage whose remembered revision is behind the current
    one is reset first, so an accepted or rejected term takes effect on old messages.

    The revision is read once, before the run, and stored for the stages that ran after it.
    A decision made while the run is in progress therefore leaves the stored revision behind
    and the next run reprocesses again, never silently skipping the new term.
    """
    stages = default_stages()
    if reset is not None:
        if reset not in {s.name for s in stages}:
            msg = f"unknown stage {reset!r}; known: {[s.name for s in stages]}"
            raise ValueError(msg)
        touched = await deps.messages.reset_stage(reset)
        log.info("pipeline.reset", stage=reset, count=touched)

    revision: int | None = None
    ran = [s for s in _LEXICON_STAGES if only is None or only == s]
    lexicon = deps.lexicon
    if lexicon is not None and ran:
        revision = await lexicon.revision()
        await _reset_stale(deps.messages, lexicon, ran, revision, already_reset=reset)

    counts = await run_pipeline(stages, deps, batch_size=batch_size, only=only)

    if lexicon is not None and revision is not None:
        for stage in ran:
            await lexicon.set_applied_revision(stage, revision)
    return counts


async def _reset_stale(
    messages: MessageRepository,
    lexicon: LexiconRepository,
    ran: list[str],
    revision: int,
    *,
    already_reset: str | None,
) -> None:
    stale: list[str] = []
    for stage in ran:
        applied = await lexicon.applied_revision(stage)
        if applied < revision:
            log.info("pipeline.lexicon_stale", stage=stage, applied=applied, revision=revision)
            stale.append(stage)
    if not stale:
        return
    first = stale[0]
    if already_reset is not None and STAGE_ORDER.index(already_reset) <= STAGE_ORDER.index(first):
        return
    touched = await messages.reset_stage(first)
    log.info("pipeline.reset", stage=first, count=touched, reason="lexicon")
