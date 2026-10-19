"""The read facade the web panel (and later the bot) calls. No logic beyond delegation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from chatradar.domain.evaluation import EvalReport, MessageLabel
    from chatradar.domain.lexicon import LexiconKind, LexiconSummary, TermPage, TermStatus
    from chatradar.domain.models import (
        ChatSummary,
        MessageFilter,
        MessagePage,
        PipelineStats,
        SearchFilters,
        Source,
        StoredMessage,
        ThreadDetail,
        ThreadHit,
    )
    from chatradar.domain.ports import (
        LabelRepository,
        LexiconRepository,
        MessageRepository,
        QueryRepository,
        SearchIndex,
        TermOrder,
    )


@dataclass(frozen=True)
class ReadServices:
    queries: QueryRepository
    search_index: SearchIndex
    stage_versions: Sequence[tuple[str, int]]  # (stage name, current version) in order
    lexicon: LexiconRepository | None = None
    labels: LabelRepository | None = None
    message_store: MessageRepository | None = None  # single-message lookup
    quality_report: Callable[[], Awaitable[EvalReport]] | None = None  # vs. human labels

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

    async def lexicon_summary(self) -> LexiconSummary:
        lexicon = _need(self.lexicon, "lexicon")
        summary = await lexicon.summary()
        labels = _need(self.labels, "labels")
        return summary.model_copy(update={"labels": await labels.count_labels()})

    async def lexicon_terms(
        self,
        *,
        kind: LexiconKind | None = None,
        status: TermStatus | None = None,
        lang: str | None = None,
        order: TermOrder = "score",
        limit: int = 100,
        offset: int = 0,
    ) -> TermPage:
        return await _need(self.lexicon, "lexicon").list_terms(
            kind=kind, status=status, lang=lang, order=order, limit=limit, offset=offset
        )

    async def label_list(self, limit: int | None = None) -> list[MessageLabel]:
        return await _need(self.labels, "labels").list_labels(limit)

    async def message(self, source: Source, chat_id: str, msg_id: str) -> StoredMessage | None:
        key = (source, chat_id, msg_id)
        return (await _need(self.message_store, "message_store").get_many([key])).get(key)

    async def quality(self) -> EvalReport:
        return await _need(self.quality_report, "quality_report")()


def _need[T](value: T | None, name: str) -> T:
    if value is None:
        raise RuntimeError(f"ReadServices was built without {name}")
    return value
