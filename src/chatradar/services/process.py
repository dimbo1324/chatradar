"""Use case: run the pipeline over everything pending, optionally after a reset."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.logs import get_logger
from chatradar.pipeline.registry import default_stages
from chatradar.pipeline.runner import run_pipeline

if TYPE_CHECKING:
    from chatradar.pipeline.base import StageDeps

log = get_logger(__name__)


async def process(
    deps: StageDeps,
    *,
    only: str | None = None,
    reset: str | None = None,
    batch_size: int = 500,
) -> dict[str, int]:
    """`reset` clears a stage (and every later one) so it reprocesses all messages."""
    stages = default_stages()
    if reset is not None:
        if reset not in {s.name for s in stages}:
            msg = f"unknown stage {reset!r}; known: {[s.name for s in stages]}"
            raise ValueError(msg)
        touched = await deps.messages.reset_stage(reset)
        log.info("pipeline.reset", stage=reset, count=touched)
    return await run_pipeline(stages, deps, batch_size=batch_size, only=only)
