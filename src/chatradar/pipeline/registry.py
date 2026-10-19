"""The stages the service runs, in `STAGE_ORDER`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.pipeline.base import STAGE_ORDER
from chatradar.pipeline.enrich import EnrichStage
from chatradar.pipeline.index import IndexStage
from chatradar.pipeline.noise import NoiseStage
from chatradar.pipeline.threads import ThreadsStage

if TYPE_CHECKING:
    from chatradar.pipeline.base import Stage


def default_stages() -> list[Stage]:
    stages: list[Stage] = [NoiseStage(), EnrichStage(), ThreadsStage(), IndexStage()]
    if tuple(s.name for s in stages) != STAGE_ORDER:
        msg = f"stages {[s.name for s in stages]} do not follow STAGE_ORDER {STAGE_ORDER}"
        raise RuntimeError(msg)
    return stages


def stage_versions() -> list[tuple[str, int]]:
    """(stage name, current version) in order, for `QueryRepository.pipeline_stats`."""
    return [(s.name, s.version) for s in default_stages()]
