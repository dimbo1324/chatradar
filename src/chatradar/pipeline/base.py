"""The pipeline stage contract. The runner arrives in roadmap step 4.

Every stage is idempotent and versioned: changed rules → `version += 1` → the
runner reprocesses only messages where `<stage>_v IS NULL OR < version`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from chatradar.domain.ports import StageResult, StoredMessage

STAGE_ORDER: tuple[str, ...] = ("normalize", "noise", "enrich", "threads", "index")


class Stage(Protocol):
    name: str
    version: int
    depends_on: str | None

    async def process(self, batch: list[StoredMessage]) -> list[StageResult]: ...
