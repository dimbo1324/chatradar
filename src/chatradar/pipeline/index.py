"""Stage `index`: rebuild the search entries of the threads whose messages changed."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatradar.domain.models import StageResult
from chatradar.domain.text import thread_id_for

if TYPE_CHECKING:
    from chatradar.pipeline.base import StageDeps

INDEX_VERSION = 2  # 2: Cyrillic yo folded to ie in the search index


class IndexStage:
    name = "index"
    version = INDEX_VERSION
    depends_on: str | None = "threads"

    async def run(self, deps: StageDeps, limit: int) -> int:
        pending = await deps.messages.pending_for(self.name, self.version, self.depends_on, limit)
        if not pending:
            return 0
        thread_ids: dict[str, None] = {}
        for msg in pending:
            if msg.thread_id is not None:
                thread_ids.setdefault(msg.thread_id, None)
            # A thread that was merged away or became noise is known by its root only; every
            # message is a possible former root, and the index drops ids that no longer exist.
            thread_ids.setdefault(thread_id_for(msg.chat_id, msg.msg_id), None)
        await deps.search.index_threads(list(thread_ids))
        await deps.messages.mark(self.name, self.version, [StageResult(key=m.key) for m in pending])
        return len(pending)
