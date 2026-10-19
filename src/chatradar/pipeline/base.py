"""Контракт стадии пайплайна. Runner появится на шаге 4 плана.

Каждая стадия идемпотентна и версионирована: смена правил → `version += 1` →
runner пересчитает только сообщения, где `<stage>_v IS NULL OR < version`.
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
