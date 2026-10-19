"""Runs the stages in order, each in batches until nothing is pending."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from chatradar.logs import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chatradar.pipeline.base import Stage, StageDeps

log = get_logger(__name__)


async def run_pipeline(
    stages: Sequence[Stage],
    deps: StageDeps,
    *,
    batch_size: int = 500,
    only: str | None = None,
) -> dict[str, int]:
    """Processed message count per stage. `only` runs one stage by name."""
    if batch_size < 1:
        msg = f"batch_size must be positive, got {batch_size}"
        raise ValueError(msg)
    selected = [s for s in stages if only is None or s.name == only]
    if not selected:
        msg = f"unknown stage {only!r}; known: {[s.name for s in stages]}"
        raise ValueError(msg)

    counts: dict[str, int] = {}
    for stage in selected:
        started = time.perf_counter()
        total = 0
        while processed := await stage.run(deps, batch_size):
            total += processed
        counts[stage.name] = total
        log.info(
            "pipeline.stage_done",
            stage=stage.name,
            version=stage.version,
            count=total,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
    return counts
