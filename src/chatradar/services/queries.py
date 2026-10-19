"""The read facade the web panel (and later the bot) calls. No logic beyond delegation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from chatradar.domain.models import (
        ChatSummary,
        MessageFilter,
        MessagePage,
        PipelineStats,
        SearchFilters,
        StoredMessage,
        ThreadDetail,
        ThreadHit,
    )
    from chatradar.domain.ports import QueryRepository, SearchIndex


@dataclass(frozen=True)
class ReadServices:
    queries: QueryRepository
    search_index: SearchIndex
    stage_versions: Sequence[tuple[str, int]]  # (stage name, current version) in order

    async def chats(self) -> list[ChatSummary]:
        return await self.queries.chat_summaries()

    async def pipeline(self) -> PipelineStats:
        return await self.queries.pipeline_stats(self.stage_versions)

    async def messages(self, filters: MessageFilter) -> MessagePage:
        return await self.queries.list_messages(filters)

    async def thread(self, thread_id: str) -> ThreadDetail | None:
        return await self.queries.get_thread(thread_id)

    async def search(self, query: str, filters: SearchFilters) -> list[ThreadHit]:
        if not query.strip():
            return []
        return await self.search_index.search(query, filters)

    async def review(self, *, is_noise: bool, n: int) -> list[StoredMessage]:
        return await self.queries.sample(is_noise=is_noise, n=n)

    async def noise_reasons(self) -> dict[str, int]:
        return await self.queries.noise_reasons()
