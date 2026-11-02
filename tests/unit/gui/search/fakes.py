"""A scripted `SearchBackend` for the Search page tests: no SQLite, no threads of its own."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from chatimport.gui.models.search_spans import find_spans
from chatimport.search_types import (
    ChatChoice,
    ContextMessage,
    IndexState,
    IndexStatus,
    SearchHit,
    SearchPage,
    SearchQuery,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def make_hit(
    msg_id: int,
    text: str = "hello world",
    *,
    chat_id: int = 1,
    title: str = "Chat one",
    age_hours: float = 1.0,
    edited: bool = False,
    link: str | None = "https://t.me/c/1/1",
) -> SearchHit:
    return SearchHit(
        chat_id=chat_id,
        chat_title=title,
        msg_id=msg_id,
        date=NOW - timedelta(hours=age_hours),
        text=text,
        edited=edited,
        link=link,
    )


def ready_status(indexed: int = 10) -> IndexStatus:
    return IndexStatus(IndexState.READY, indexed, indexed, NOW)


@dataclass
class FakeBackend:
    hits: Sequence[SearchHit] = ()
    chat_list: Sequence[ChatChoice] = ()
    index_status: IndexStatus = field(default_factory=ready_status)
    neighbours: Sequence[ContextMessage] | None = None
    fail_search: bool = False
    fail_status: bool = False
    fail_context: bool = False
    queries: list[SearchQuery] = field(default_factory=list[SearchQuery])
    context_calls: list[tuple[int, int, int, int]] = field(
        default_factory=list[tuple[int, int, int, int]]
    )
    threads: set[int] = field(default_factory=set[int])
    status_calls: int = 0
    closed: bool = False

    def search(self, query: SearchQuery) -> SearchPage:
        self.threads.add(threading.get_ident())
        self.queries.append(query)
        if self.fail_search:
            raise RuntimeError("scripted failure")
        matching = [
            hit
            for hit in self.hits
            if find_spans(hit.text, query.text)
            and (query.chat_ids is None or hit.chat_id in query.chat_ids)
            and (query.since is None or hit.date >= query.since)
            and (query.until is None or hit.date < query.until)
        ]
        matching.sort(key=lambda hit: (hit.date, hit.msg_id), reverse=True)
        window = matching[query.offset : query.offset + query.limit]
        return SearchPage(tuple(window), len(matching), query)

    def context(
        self, chat_id: int, msg_id: int, before: int = 3, after: int = 3
    ) -> tuple[ContextMessage, ...]:
        self.threads.add(threading.get_ident())
        self.context_calls.append((chat_id, msg_id, before, after))
        if self.fail_context:
            raise RuntimeError("scripted failure")
        if self.neighbours is not None:
            return tuple(self.neighbours)
        return tuple(
            ContextMessage(hit.msg_id, hit.date, hit.text, hit.edited, hit.msg_id == msg_id)
            for hit in sorted(self.hits, key=lambda h: h.msg_id)
            if hit.chat_id == chat_id and abs(hit.msg_id - msg_id) <= max(before, after)
        )

    def chats(self) -> tuple[ChatChoice, ...]:
        self.threads.add(threading.get_ident())
        return tuple(self.chat_list)

    def status(self) -> IndexStatus:
        self.threads.add(threading.get_ident())
        self.status_calls += 1
        if self.fail_status:
            raise RuntimeError("scripted failure")
        return self.index_status

    def close(self) -> None:
        self.closed = True
