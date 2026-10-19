"""In-memory `QueryRepository` and `SearchIndex` for web tests, recording every call."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from chatradar.domain.models import (
    ChatInfo,
    ChatSummary,
    MessageFilter,
    MessagePage,
    PipelineStats,
    SearchFilters,
    Source,
    StageStat,
    StoredMessage,
    Thread,
    ThreadDetail,
    ThreadHit,
)
from chatradar.domain.text import content_hash
from chatradar.services.queries import ReadServices

if TYPE_CHECKING:
    from collections.abc import Sequence

START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CHAT = ChatInfo(source=Source.TELEGRAM, chat_id="-100500", title="Synthetic chat", username="demo")
STAGES = (("normalize", 1), ("noise", 1), ("enrich", 1), ("threads", 1), ("index", 1))


def message(
    msg_id: int,
    text: str,
    *,
    minutes: int = 0,
    chat: ChatInfo = CHAT,
    reply_to: int | None = None,
    thread_id: str | None = None,
    noise_reason: str | None = None,
    is_question: bool = False,
    lang: str | None = "ru",
) -> StoredMessage:
    return StoredMessage(
        source=chat.source,
        chat_id=chat.chat_id,
        msg_id=str(msg_id),
        author_id=None,
        date=START + timedelta(minutes=minutes),
        text=text,
        text_raw=text,
        reply_to=str(reply_to) if reply_to is not None else None,
        link=f"https://t.me/{chat.username}/{msg_id}" if chat.username else None,
        content_hash=content_hash(text_raw=text, media_type="none", reply_to=None),
        lang=lang,
        is_question=is_question,
        is_noise=noise_reason is not None,
        noise_reason=noise_reason,
        thread_id=thread_id,
    )


def thread_of(messages: Sequence[StoredMessage]) -> Thread:
    root = messages[0]
    return Thread(
        thread_id=f"{root.chat_id}:{root.msg_id}",
        source=root.source,
        chat_id=root.chat_id,
        root_msg_id=root.msg_id,
        started_at=messages[0].date,
        ended_at=messages[-1].date,
        msg_count=len(messages),
        has_question=any(m.is_question for m in messages),
    )


class FakeQueries:
    def __init__(
        self,
        chats: Sequence[ChatInfo],
        messages: Sequence[StoredMessage],
        threads: Sequence[Thread],
    ) -> None:
        self.chats = list(chats)
        self.messages = sorted(messages, key=lambda m: m.date)
        self.threads = {t.thread_id: t for t in threads}
        self.calls: list[tuple[str, Any]] = []

    async def chat_summaries(self) -> list[ChatSummary]:
        self.calls.append(("chat_summaries", None))
        summaries: list[ChatSummary] = []
        for chat in self.chats:
            own = [m for m in self.messages if m.chat_id == chat.chat_id]
            summaries.append(
                ChatSummary(
                    chat=chat,
                    message_count=len(own),
                    noise_count=sum(1 for m in own if m.is_noise),
                    thread_count=sum(1 for t in self.threads.values() if t.chat_id == chat.chat_id),
                    first_message_at=own[0].date if own else None,
                    last_message_at=own[-1].date if own else None,
                    last_sync_at=START + timedelta(days=1) if own else None,
                )
            )
        return summaries

    async def pipeline_stats(self, stage_versions: Sequence[tuple[str, int]]) -> PipelineStats:
        self.calls.append(("pipeline_stats", list(stage_versions)))
        total = len(self.messages)
        stages = [
            StageStat(stage=name, version=version, done=total - i, pending=i)
            for i, (name, version) in enumerate(stage_versions)
        ]
        return PipelineStats(total_messages=total, stages=stages)

    async def list_messages(self, filters: MessageFilter) -> MessagePage:
        self.calls.append(("list_messages", filters))
        wanted = {
            "source": filters.source,
            "chat_id": filters.chat_id,
            "lang": filters.lang,
            "is_noise": filters.is_noise,
            "noise_reason": filters.noise_reason,
            "is_question": filters.is_question,
            "thread_id": filters.thread_id,
        }
        found = [
            m
            for m in self.messages
            if all(v is None or getattr(m, k) == v for k, v in wanted.items())
            and (filters.date_from is None or m.date >= filters.date_from)
            and (filters.date_to is None or m.date <= filters.date_to)
        ]
        page = found[filters.offset : filters.offset + filters.limit]
        return MessagePage(items=page, total=len(found), limit=filters.limit, offset=filters.offset)

    async def get_thread(self, thread_id: str) -> ThreadDetail | None:
        self.calls.append(("get_thread", thread_id))
        thread = self.threads.get(thread_id)
        if thread is None:
            return None
        members = [m for m in self.messages if m.thread_id == thread_id]
        return ThreadDetail(thread=thread, messages=members)

    async def sample(self, *, is_noise: bool, n: int) -> list[StoredMessage]:
        self.calls.append(("sample", (is_noise, n)))
        pool = [m for m in self.messages if bool(m.is_noise) == is_noise]
        return pool[:n]

    async def noise_reasons(self) -> dict[str, int]:
        self.calls.append(("noise_reasons", None))
        counts: dict[str, int] = {}
        for m in self.messages:
            if m.noise_reason:
                counts[m.noise_reason] = counts.get(m.noise_reason, 0) + 1
        return counts


class FakeSearch:
    def __init__(self, queries: FakeQueries) -> None:
        self.queries = queries
        self.calls: list[tuple[str, SearchFilters]] = []

    async def index_threads(self, thread_ids: Sequence[str]) -> None:
        return None

    async def rebuild(self) -> None:
        return None

    async def search(self, query: str, filters: SearchFilters) -> list[ThreadHit]:
        self.calls.append((query, filters))
        words = [w for w in re.findall(r"\w+", query.lower()) if w]
        hits: list[ThreadHit] = []
        for thread in self.queries.threads.values():
            if filters.chat_id is not None and thread.chat_id != filters.chat_id:
                continue
            text = " ".join(
                m.text for m in self.queries.messages if m.thread_id == thread.thread_id
            )
            score = sum(text.lower().count(w) for w in words)
            if score == 0:
                continue
            pattern = re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE)
            snippet = pattern.sub(lambda match: f"[[{match.group(0)}]]", text[:200])
            root = next(m for m in self.queries.messages if m.msg_id == thread.root_msg_id)
            hits.append(ThreadHit(thread=thread, score=score, snippet=snippet, link=root.link))
        hits.sort(key=lambda hit: -hit.score)
        return hits[: filters.limit]


def sample_data() -> tuple[list[ChatInfo], list[StoredMessage], list[Thread]]:
    tid = f"{CHAT.chat_id}:1"
    question = message(1, "Where to renew a residence permit?", thread_id=tid, is_question=True)
    reply = message(2, "At the migration office, book online", minutes=5, reply_to=1, thread_id=tid)
    nested = message(3, "Online booking works, <b>tested</b>", minutes=9, reply_to=2, thread_id=tid)
    noise = message(4, "+1", minutes=12, noise_reason="short")
    messages = [question, reply, nested, noise]
    return [CHAT], messages, [thread_of([question, reply, nested])]


def build_read_services(
    chats: Sequence[ChatInfo] | None = None,
    messages: Sequence[StoredMessage] | None = None,
    threads: Sequence[Thread] | None = None,
) -> tuple[ReadServices, FakeQueries, FakeSearch]:
    default_chats, default_messages, default_threads = sample_data()
    queries = FakeQueries(
        default_chats if chats is None else chats,
        default_messages if messages is None else messages,
        default_threads if threads is None else threads,
    )
    search = FakeSearch(queries)
    return (
        ReadServices(queries=queries, search_index=search, stage_versions=STAGES),
        queries,
        search,
    )
